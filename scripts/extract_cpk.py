"""
碧蓝航线 USM (CRI) 解复用器
从 .bytes (USM) 文件中提取视频和音频流
"""

import struct
import os
import sys as _p_sys, os as _p_os
_p_sys.path.insert(0, _p_os.path.dirname(_p_os.path.abspath(__file__)))
import paths as P  # 仓库根与外部工具位置：见 scripts/paths.py（AL_ASSETS_ROOT 可覆盖）
import subprocess

FFMPEG = P.FFMPEG

# 碧蓝航线 HCA 密钥
HCA_KEY = bytes.fromhex("95356C720002354E")


def find_streams(data):
    """在 USM 数据中查找流标记"""
    streams = []
    i = 0
    while i < len(data) - 4:
        marker = data[i:i+4]
        if marker == b'@SFV':
            streams.append({'type': 'video', 'offset': i})
        elif marker == b'@SFA':
            streams.append({'type': 'audio', 'offset': i})
        elif marker == b'@SFP':
            streams.append({'type': 'packet', 'offset': i})
        i += 1
    return streams


def extract_raw_streams(data, output_dir, base_name):
    """提取原始流数据"""
    streams = find_streams(data)
    results = []
    
    for idx, stream in enumerate(streams):
        start = stream['offset']
        # 找到下一个流标记或文件末尾
        end = len(data)
        for i in range(start + 4, len(data) - 4):
            if data[i:i+4] in [b'@SFV', b'@SFA', b'@SFP', b'CRID']:
                end = i
                break
        
        stream_data = data[start:end]
        ext = '.m1v' if stream['type'] == 'video' else '.adx'
        out_path = os.path.join(output_dir, f"{base_name}_stream{idx}{ext}")
        
        with open(out_path, 'wb') as f:
            f.write(stream_data)
        
        results.append({
            'type': stream['type'],
            'path': out_path,
            'size': len(stream_data),
        })
        print(f"  Stream {idx}: {stream['type']} -> {out_path} ({len(stream_data)/1024:.0f} KB)")
    
    return results


def try_ffmpeg_demux(input_path, output_dir, base_name):
    """尝试用 ffmpeg 解复用"""
    if not FFMPEG:
        print("  缺 ffmpeg：设环境变量 AL_FFMPEG 指向 ffmpeg.exe 再跑（本步跳过）")
        return False
    video_out = os.path.join(output_dir, f"{base_name}.mpg")
    audio_out = os.path.join(output_dir, f"{base_name}.wav")

    # 两个 map 各出各的：USM 里视频/音频是**独立流**，只给一个输出文件时
    # ffmpeg 会把音频丢掉（`-c:a pcm_s16le` 只作用于被选中的输出流）。
    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-map", "0:v:0", "-c:v", "mpeg1video", video_out,
        "-map", "0:a:0", "-c:a", "pcm_s16le", audio_out,
    ]

    ok_video = False
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        if result.returncode == 0 and os.path.exists(video_out):
            print(f"  ffmpeg 成功: {video_out}")
            ok_video = True
        if os.path.exists(audio_out):
            print(f"  ffmpeg 成功: {audio_out}")
            ok_video = ok_video or True
    except Exception as e:
        print(f"  ffmpeg 失败: {e}")

    return ok_video


def process_cpk_dir(cpk_dir, output_dir):
    """处理整个 CPK 目录"""
    os.makedirs(output_dir, exist_ok=True)
    
    cpk_files = [f for f in os.listdir(cpk_dir) if f.endswith('.cpk')]
    print(f"找到 {len(cpk_files)} 个 CPK 文件\n")
    
    success = 0
    failed = []
    
    for i, cpk_name in enumerate(cpk_files):
        cpk_path = os.path.join(cpk_dir, cpk_name)
        base_name = os.path.splitext(cpk_name)[0]
        
        print(f"[{i+1}/{len(cpk_files)}] {cpk_name}")
        
        # Step 1: 用 CriPakTools 解压 CPK
        unpack_dir = os.path.join(cpk_dir, f"{base_name}_unpack")
        bytes_file = os.path.join(unpack_dir, f"{base_name}.bytes")
        
        if not os.path.exists(bytes_file):
            CRIPAK = P.tool("AL_CRIPAK", "CriPakTools",
                            os.path.join(P.ROOT, "tools", "CriPakTools", "CriPakTools.exe"))
            if not CRIPAK:
                print("  缺 CriPakTools：设环境变量 AL_CRIPAK 指向 CriPakTools.exe 再跑")
                failed.append(cpk_name)
                continue
            cmd = [CRIPAK, cpk_path, "all"]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60)
            except Exception as e:
                print(f"  CriPakTools 失败: {e}")
                failed.append(cpk_name)
                continue
        
        if not os.path.exists(bytes_file):
            print(f"  未找到 .bytes 文件")
            failed.append(cpk_name)
            continue
        
        # Step 2: 尝试 ffmpeg 解复用
        print(f"  尝试 ffmpeg 解复用...")
        if try_ffmpeg_demux(bytes_file, output_dir, base_name):
            success += 1
            continue
        
        # Step 3: 提取原始流
        print(f"  ffmpeg 失败，提取原始流...")
        with open(bytes_file, 'rb') as f:
            data = f.read()
        
        streams = extract_raw_streams(data, output_dir, base_name)
        if streams:
            success += 1
        else:
            failed.append(cpk_name)
    
    print(f"\n{'='*60}")
    print(f"成功: {success}, 失败: {len(failed)}")
    if failed:
        print(f"失败文件: {', '.join(failed[:10])}")


if __name__ == "__main__":
    cpk_dir = os.path.join(P.AB, "originsource", "cpk")
    output_dir = os.path.join(P.OUT, "CPK")
    process_cpk_dir(cpk_dir, output_dir)
