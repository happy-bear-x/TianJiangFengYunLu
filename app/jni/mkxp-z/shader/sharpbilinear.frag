/* Sharp-bilinear: final window blit for the HD path.
 *
 * The game canvas is 853x480 and the window is whatever the device gives
 * us (1280x720 in the emulator, 2340x1080 on a typical phone), so the
 * last blit is almost never an integer scale. Plain nearest then makes
 * some source pixels one screen pixel wide and their neighbours two,
 * which shows up as jitter along every edge; plain bilinear fixes the
 * jitter but smears the whole image.
 *
 * This limits the interpolation band to half a destination pixel around
 * each source texel centre. Inside the band we blend, outside we snap to
 * the centre: edges stay crisp, while the pixel grid advances evenly.
 * At 1:1 the band collapses to a single point and this is exact nearest.
 * When the destination is smaller than the source the band exceeds the
 * texel, so it degrades to ordinary bilinear -- which is the right
 * behaviour for downscaling anyway.
 */

#ifdef GL_FRAGMENT_PRECISION_HIGH
/* A 2340px destination needs 12 bits; mediump quantises the texel grid
 * and makes edges shimmer while scrolling. */
precision highp float;
#else
precision mediump float;
#endif

uniform sampler2D texture;
uniform vec2 texSize;   /* source size in pixels */
uniform vec2 destSize;  /* destination size in pixels */

varying vec2 v_texCoord;

void main()
{
	vec2 scale = destSize / texSize;

	/* Downscale path. The canvas is a supersampled buffer (2x the logical
	 * resolution) and the window is smaller, so this blit averages ~1.33x1.33
	 * source texels per destination pixel. The texture filter on this path is
	 * GL_NEAREST, so plain texture2D() here would drop 1 of every 4 pixels and
	 * show up as ragged steps along every diagonal. Blend the 2x2 neighbourhood
	 * explicitly instead -- that turns the 2x canvas into a proper supersampled
	 * downsample and leaves the pixel art edges smooth rather than shattered. */
	if (scale.x < 1.0 || scale.y < 1.0)
	{
		vec2 texel = 1.0 / texSize;
		vec2 pos = v_texCoord * texSize - 0.5;
		vec2 f = fract(pos);
		vec2 base = (floor(pos) + 0.5) * texel;

		vec4 c00 = texture2D(texture, base);
		vec4 c10 = texture2D(texture, base + vec2(texel.x, 0.0));
		vec4 c01 = texture2D(texture, base + vec2(0.0, texel.y));
		vec4 c11 = texture2D(texture, base + texel);

		gl_FragColor = mix(mix(c00, c10, f.x), mix(c01, c11, f.x), f.y);
		return;
	}

	vec2 pos = v_texCoord * texSize;

	/* Half-width of the blend band, in fractions of one source texel.
	 * scale >= 1 -> <= 0.5 (sharp); scale < 1 -> > 0.5, band covers the
	 * whole texel and clamp() below becomes a no-op. */
	vec2 halfBand = 0.5 / scale;

	vec2 frac = fract(pos);
	vec2 clampedFrac = clamp(frac, 0.5 - halfBand, 0.5 + halfBand);

	vec2 uv = (floor(pos) + clampedFrac) / texSize;

	gl_FragColor = texture2D(texture, clamp(uv, vec2(0.0), vec2(1.0)));
}
