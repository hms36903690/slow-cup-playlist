#!/usr/bin/env python3
"""
Slow Cup Jazz - 플레이리스트 영상 자동 제작 스크립트 (원래 Window Seat Café용으로 만든 것)

하는 일 (명령어 한 번으로):
  1. 폴더 안의 음악 파일을 이름 순서대로 이어 붙입니다 (곡 사이 크로스페이드)
  2. 처음 페이드인, 마지막 페이드아웃을 넣습니다
  3. 유튜브 기준 음량(-14 LUFS)으로 맞춥니다
  4. 유튜브 설명란에 붙일 타임스탬프(챕터)를 만듭니다
  5. 배경 이미지와 합쳐 1080p 영상(mp4)을 만듭니다

필요한 것: Python 3, ffmpeg (무료)

사용 예:
  python3 playlist_maker.py 음악폴더 --image 배경.jpg
  python3 playlist_maker.py 음악폴더 --image 배경.jpg --crossfade 3 --out 겨울재즈

결과물 (--out 이름 기준):
  겨울재즈_mix.m4a        합쳐진 음원
  겨울재즈_timestamps.txt 설명란용 타임스탬프
  겨울재즈.mp4            업로드용 영상 (--image 를 줬을 때)
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-3000:])
        sys.exit(f"\n[오류] 실행 실패: {' '.join(cmd[:3])} ...")
    return p


def duration(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)])
    return float(json.loads(p.stdout)["format"]["duration"])


def natural_key(p):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def clean_title(p):
    # "01_Steam over the Cup.mp3" -> "Steam over the Cup"
    name = re.sub(r"^\s*\d+\s*[-_.)\]]*\s*", "", p.stem)
    return name.replace("_", " ").strip() or p.stem


def fmt(sec, long_fmt):
    sec = int(round(sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if long_fmt else f"{m:02d}:{s:02d}"


def main():
    ap = argparse.ArgumentParser(description="플레이리스트 음원·타임스탬프·영상 자동 제작")
    ap.add_argument("folder", help="음악 파일이 들어 있는 폴더 (파일 이름 순서대로 이어 붙임)")
    ap.add_argument("--image", help="배경 이미지 (jpg/png). 주면 mp4 영상까지 만듭니다")
    ap.add_argument("--crossfade", type=float, default=3.0, help="곡 사이 겹치는 시간(초), 기본 3")
    ap.add_argument("--fade-in", type=float, default=3.0, help="시작 페이드인(초), 기본 3")
    ap.add_argument("--fade-out", type=float, default=8.0, help="끝 페이드아웃(초), 기본 8")
    ap.add_argument("--lufs", type=float, default=-14.0, help="목표 음량, 기본 -14 LUFS")
    ap.add_argument("--out", default="playlist", help="결과 파일 이름 앞부분, 기본 playlist")
    a = ap.parse_args()

    folder = Path(a.folder)
    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in AUDIO_EXT], key=natural_key)
    if len(files) < 1:
        sys.exit("[오류] 폴더에 음악 파일(mp3/wav/m4a/flac)이 없습니다.")

    print(f"🎵 {len(files)}곡 확인 중...")
    durs = [duration(f) for f in files]
    xf = max(0.0, a.crossfade)
    if len(files) > 1 and xf >= min(durs) / 2:
        sys.exit("[오류] 크로스페이드가 너무 깁니다. --crossfade 값을 줄이세요.")

    # 1) 곡 시작 시간 계산 → 타임스탬프
    starts, t = [], 0.0
    for i, d in enumerate(durs):
        starts.append(t)
        t += d - (xf if i < len(durs) - 1 else 0)
    total = t
    long_fmt = total >= 3600
    lines = [f"{fmt(s, long_fmt)} {clean_title(f)}" for s, f in zip(starts, files)]
    ts_path = Path(f"{a.out}_timestamps.txt")
    ts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 2) 음원 합치기 + 페이드 + 음량 맞추기 (한 번에)
    inputs = []
    for f in files:
        inputs += ["-i", str(f)]
    if len(files) == 1 or xf == 0:
        n = len(files)
        chain = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[m]"
    else:
        parts, prev = [], "[0:a]"
        for i in range(1, len(files)):
            out = f"[x{i}]"
            parts.append(f"{prev}[{i}:a]acrossfade=d={xf}:c1=tri:c2=tri{out}")
            prev = out
        chain = ";".join(parts) + f";{prev}anull[m]"
    fo_start = max(0.0, total - a.fade_out)
    chain += (f";[m]afade=t=in:d={a.fade_in},afade=t=out:st={fo_start:.2f}:d={a.fade_out},"
              f"loudnorm=I={a.lufs}:TP=-1.5:LRA=11,aresample=48000[out]")
    mix = Path(f"{a.out}_mix.m4a")
    print(f"🎚  합치는 중... (총 {fmt(total, True)})")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", chain,
         "-map", "[out]", "-c:a", "aac", "-b:a", "320k", str(mix)])

    # 3) 영상 만들기 (정지 이미지 + 음원, 빠른 렌더링)
    if a.image:
        video = Path(f"{a.out}.mp4")
        print("🎬 영상 만드는 중...")
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", a.image,
             "-i", str(mix),
             "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,format=yuv420p",
             "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-r", "24",
             "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(video)])
        print(f"✅ 영상: {video}")

    print(f"✅ 음원: {mix}")
    print(f"✅ 타임스탬프: {ts_path}\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
