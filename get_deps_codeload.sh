#!/bin/bash
# 通过 codeload 拉 tarball 获取依赖（代理对 github.com 的 CONNECT 返回 502，
# 但 codeload.github.com 可用）。上游 get_deps.sh 的 git clone 在此网络环境下走不通。
set -u
cd "$(dirname "$0")/app/jni" || exit 1

fetch() {  # fetch <dir> <owner/repo> <tag>
  local d=$1 repo=$2 tag=$3
  [ -d "$d" ] && { echo "skip $d"; return 0; }
  echo ">>> $d  ($repo @ $tag)"
  local tmp="/tmp/dep_$d.tgz"
  if ! curl -sSL --max-time 420 -o "$tmp" \
      "https://codeload.github.com/$repo/tar.gz/refs/tags/$tag"; then
    echo "    FAIL download $d"; return 1
  fi
  local sz; sz=$(stat -c%s "$tmp" 2>/dev/null || echo 0)
  if [ "$sz" -lt 20000 ]; then
    echo "    FAIL suspicious size $sz"; head -c 200 "$tmp"; echo; return 1
  fi
  mkdir -p "$d"
  tar -xzf "$tmp" -C "$d" --strip-components=1 && rm -f "$tmp" && \
    echo "    ok $(du -sh "$d" | cut -f1)" || { echo "    FAIL extract"; return 1; }
}

fetch libogg       xiph/ogg              v1.3.5
fetch libvorbis    xiph/vorbis           v1.3.7
fetch libtheora    xiph/theora           v1.1.1
fetch physfs       icculus/physfs        release-3.2.0
fetch openal       kcat/openal-soft      1.23.0
fetch SDL2         libsdl-org/SDL        release-2.26.3
fetch SDL2_image   libsdl-org/SDL_image  release-2.6.3
fetch SDL2_ttf     libsdl-org/SDL_ttf    release-2.20.2
fetch SDL2_sound   icculus/SDL_sound     v2.0.1
fetch openssl      openssl/openssl       OpenSSL_1_1_1t
fetch ruby         mkxp-z/ruby           mkxp-z-3.1

echo "=== 结果 ==="
for d in libogg libvorbis libtheora libiconv uchardet pixman physfs openal SDL2 SDL2_image SDL2_ttf SDL2_sound openssl ruby; do
  [ -d "$d" ] && printf "  ok   %-12s %s\n" "$d" "$(du -sh "$d" 2>/dev/null | cut -f1)" || printf "  MISS %s\n" "$d"
done
