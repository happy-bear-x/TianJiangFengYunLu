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
 * When the destination is smaller than the source (the usual HD case: a
 * 2x canvas squeezed into a smaller window) we switch to a 6x6 Lanczos-3
 * filter instead, whose wider support and negative lobes both suppress the
 * stair-steps and keep sprite outlines resolved rather than smeared.
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

/* Lanczos-2 kernel. Used only on the downscale path: the canvas is 2x the
 * logical resolution and the window is smaller, so this blit has to average
 * ~1.33 source texels per destination pixel.
 *
 * A 2x2 bilinear tap is far too narrow for that footprint. Catmull-Rom (4x4)
 * fixed most of the stair-steps but leaves sprite outlines slightly soft: it
 * has no negative lobe, so every edge gets averaged instead of resolved.
 *
 * Lanczos-2 keeps the same 4x4 support (so the kernel width still matches the
 * 1.33 texel footprint -- Lanczos-3 was tried and came out *softer*, because
 * its radius-3 support over-covers the footprint) while adding the negative
 * lobe that restores edge contrast. On sprite contours that is the difference
 * between a grey smear and a solid black line.
 *
 * The lobe overshoots around hard edges (ringing), so the result is clamped
 * back into [0,1] below. On flat-colour pixel art the overshoot is small and
 * only shows as a subtle edge crispening. */
float tjLz2Weight(float x)
{
	float ax = abs(x);
	if (ax < 0.0001)
		return 1.0;
	if (ax >= 2.0)
		return 0.0;
	float px = 3.14159265 * ax;
	return 2.0 * sin(px) * sin(px * 0.5) / (px * px);
}

void main()
{
	vec2 scale = destSize / texSize;

	if (scale.x < 1.0 || scale.y < 1.0)
	{
		vec2 pos = v_texCoord * texSize - 0.5;
		vec2 base = floor(pos);
		vec2 f = pos - base;

		/* Stretch the kernel by the downscale factor. This is the part that
		 * matters: a fixed-width kernel over a 1.33-texel footprint either
		 * under-covers (stairsteps) or over-covers (smear). Scaling the
		 * argument by `s` makes the filter's effective width track the
		 * footprint exactly, which is what a proper resampling filter does. */
		float s = min(scale.x, scale.y);

		/* Keep the taps on texel centres: with GL_NEAREST on this texture,
		 * sampling at exactly 1.0 would wrap to the far edge. */
		vec2 lo = 0.5 / texSize;
		vec2 hi = 1.0 - lo;

		vec4 sum = vec4(0.0);
		float wsum = 0.0;

		/* 4x4 support (radius 2, taps -1..+2 about the sample position). */
		for (int j = -1; j <= 2; ++j)
		{
			float wy = tjLz2Weight((float(j) - f.y) * s);
			for (int i = -1; i <= 2; ++i)
			{
				float w = tjLz2Weight((float(i) - f.x) * s) * wy;
				vec2 p = (base + vec2(float(i), float(j)) + 0.5) / texSize;
				sum += texture2D(texture, clamp(p, lo, hi)) * w;
				wsum += w;
			}
		}

		/* Negative lobes push values outside [0,1] on hard edges. */
		gl_FragColor = clamp(sum / max(wsum, 0.0001), 0.0, 1.0);
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
