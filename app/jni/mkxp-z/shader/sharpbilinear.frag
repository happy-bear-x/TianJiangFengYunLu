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
 * 2x canvas squeezed into a smaller window) we switch to a 4x4 Catmull-Rom
 * filter instead, which is wide enough to actually suppress the stair-steps
 * without smearing the pixel art the way plain bilinear does.
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

/* Catmull-Rom kernel. Used only on the downscale path: the canvas is 2x the
 * logical resolution and the window is smaller, so this blit has to average
 * ~1.33 source texels per destination pixel. A 2x2 bilinear tap is too narrow
 * for that footprint -- it keeps the stair-steps on every sprite outline and
 * leaves the pixel blocks uneven -- so we use the full 4x4 support. */
float tjCrWeight(float x)
{
	float ax = abs(x);
	if (ax <= 1.0)
		return 1.5*ax*ax*ax - 2.5*ax*ax + 1.0;
	if (ax <= 2.0)
		return -0.5*ax*ax*ax + 2.5*ax*ax - 4.0*ax + 2.0;
	return 0.0;
}

void main()
{
	vec2 scale = destSize / texSize;

	if (scale.x < 1.0 || scale.y < 1.0)
	{
		vec2 pos = v_texCoord * texSize - 0.5;
		vec2 base = floor(pos);
		vec2 f = pos - base;

		/* Keep the taps on texel centres: with GL_NEAREST on this texture,
		 * sampling at exactly 1.0 would wrap to the far edge. */
		vec2 lo = 0.5 / texSize;
		vec2 hi = 1.0 - lo;

		vec4 sum = vec4(0.0);
		float wsum = 0.0;

		for (int j = -1; j <= 2; ++j)
		{
			float wy = tjCrWeight(float(j) - f.y);
			for (int i = -1; i <= 2; ++i)
			{
				float w = tjCrWeight(float(i) - f.x) * wy;
				vec2 p = (base + vec2(float(i), float(j)) + 0.5) / texSize;
				sum += texture2D(texture, clamp(p, lo, hi)) * w;
				wsum += w;
			}
		}

		gl_FragColor = sum / max(wsum, 0.0001);
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
