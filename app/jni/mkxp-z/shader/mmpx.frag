/* MMPX 2x upscaler.
 *
 * Algorithm: "Pixel Art with Refined Composition" (McGuire & Gagiu, JCGT 2021).
 * Ported line-by-line from the official MMPX.glc compute shader to a
 * GLSL ES 1.0 fragment shader, because the Android build runs GLES2 and
 * has no compute shaders or texelFetch.
 *
 * Contract: the destination rectangle must be exactly 2x the source
 * rectangle. Each source texel becomes a 2x2 block; the block corner is
 * selected by the parity of the destination pixel.
 *
 * v_texCoord comes from simple.vert (texCoord * texSizeInv), so it is
 * normalized [0,1] and interpolated across the destination quad. Every
 * neighbour lookup below is clamped by hand instead of relying on the
 * texture wrap mode.
 */

#ifdef GL_FRAGMENT_PRECISION_HIGH
/* 1706 destination pixels need 11 bits; mediump (10 bit) would quantize
 * the parity and shift whole columns. */
precision highp float;
#else
precision mediump float;
#endif

uniform sampler2D texture;
uniform vec2 texSize;

varying vec2 v_texCoord;

vec4 S(float x, float y)
{
	vec2 p = (clamp(vec2(x, y), vec2(0.0), texSize - 1.0) + 0.5) / texSize;
	return texture2D(texture, p);
}

bool EQ(vec4 a, vec4 b)
{
	return all(lessThan(abs(a - b), vec4(0.0020)));
}

bool allEQ2(vec4 b, vec4 a0, vec4 a1)
{
	return EQ(b, a0) && EQ(b, a1);
}

bool allEQ3(vec4 b, vec4 a0, vec4 a1, vec4 a2)
{
	return EQ(b, a0) && EQ(b, a1) && EQ(b, a2);
}

bool allEQ4(vec4 b, vec4 a0, vec4 a1, vec4 a2, vec4 a3)
{
	return EQ(b, a0) && EQ(b, a1) && EQ(b, a2) && EQ(b, a3);
}

bool anyEQ3(vec4 b, vec4 a0, vec4 a1, vec4 a2)
{
	return EQ(b, a0) || EQ(b, a1) || EQ(b, a2);
}

bool noneEQ2(vec4 b, vec4 a0, vec4 a1)
{
	return !EQ(b, a0) && !EQ(b, a1);
}

bool noneEQ4(vec4 b, vec4 a0, vec4 a1, vec4 a2, vec4 a3)
{
	return !EQ(b, a0) && !EQ(b, a1) && !EQ(b, a2) && !EQ(b, a3);
}

float lum(vec4 c)
{
	return (c.r + c.g + c.b + 0.00392157) * (1.0 - c.a);
}

void main()
{
	/* Destination pixel index and the source texel it belongs to */
	vec2 dst = floor(v_texCoord * texSize * 2.0);
	float sx = floor(dst.x * 0.5);
	float sy = floor(dst.y * 0.5);

	vec4 A = S(sx-1.0, sy-1.0), B = S(sx, sy-1.0), C = S(sx+1.0, sy-1.0);
	vec4 D = S(sx-1.0, sy    ), E = S(sx, sy    ), F = S(sx+1.0, sy    );
	vec4 G = S(sx-1.0, sy+1.0), H = S(sx, sy+1.0), I = S(sx+1.0, sy+1.0);

	vec4 J = E, K = E, L = E, M = E;

	bool isFlat = EQ(A,E) && EQ(B,E) && EQ(C,E) && EQ(D,E)
	           && EQ(F,E) && EQ(G,E) && EQ(H,E) && EQ(I,E);

	if (!isFlat)
	{
		vec4 P = S(sx, sy-2.0), Q = S(sx-2.0, sy);
		vec4 R = S(sx+2.0, sy), T = S(sx, sy+2.0);

		float Bl = lum(B), Dl = lum(D), El = lum(E), Fl = lum(F), Hl = lum(H);

		if (EQ(D,B) && !EQ(D,H) && !EQ(D,F) && (El >= Dl || EQ(E,A))
		    && anyEQ3(E,A,C,G) && (El < Dl || !EQ(A,D) || !EQ(E,P) || !EQ(E,Q)))
			J = D;

		if (EQ(B,F) && !EQ(B,D) && !EQ(B,H) && (El >= Bl || EQ(E,C))
		    && anyEQ3(E,A,C,I) && (El < Bl || !EQ(C,B) || !EQ(E,P) || !EQ(E,R)))
			K = B;

		if (EQ(H,D) && !EQ(H,F) && !EQ(H,B) && (El >= Hl || EQ(E,G))
		    && anyEQ3(E,A,G,I) && (El < Hl || !EQ(G,H) || !EQ(E,T) || !EQ(E,Q)))
			L = H;

		if (EQ(F,H) && !EQ(F,B) && !EQ(F,D) && (El >= Fl || EQ(E,I))
		    && anyEQ3(E,C,G,I) && (El < Fl || !EQ(I,H) || !EQ(E,R) || !EQ(E,T)))
			M = F;

		if (!EQ(E,F) && allEQ4(E,C,I,D,Q) && allEQ2(F,B,H)
		    && !EQ(F, S(sx+3.0, sy))) { K = F; M = F; }

		if (!EQ(E,D) && allEQ4(E,A,G,F,R) && allEQ2(D,B,H)
		    && !EQ(D, S(sx-3.0, sy))) { J = D; L = D; }

		if (!EQ(E,H) && allEQ4(E,G,I,B,P) && allEQ2(H,D,F)
		    && !EQ(H, S(sx, sy+3.0))) { L = H; M = H; }

		if (!EQ(E,B) && allEQ4(E,A,C,H,T) && allEQ2(B,D,F)
		    && !EQ(B, S(sx, sy-3.0))) { J = B; K = B; }

		if (Bl < El && allEQ4(E,G,H,I,T) && noneEQ4(E,A,D,C,F)) { J = B; K = B; }
		if (Hl < El && allEQ4(E,A,B,C,P) && noneEQ4(E,D,G,I,F)) { L = H; M = H; }
		if (Fl < El && allEQ4(E,A,D,G,Q) && noneEQ4(E,B,C,I,H)) { K = F; M = F; }
		if (Dl < El && allEQ4(E,C,F,I,R) && noneEQ4(E,B,A,G,H)) { J = D; L = D; }

		if (!EQ(H,B))
		{
			if (!EQ(H,A) && !EQ(H,E) && !EQ(H,C))
			{
				if (allEQ3(H,G,F,R) && noneEQ2(H,D, S(sx+2.0, sy-1.0))) { L = M; }
				if (allEQ3(H,I,D,Q) && noneEQ2(H,F, S(sx-2.0, sy-1.0))) { M = L; }
			}
			if (!EQ(B,I) && !EQ(B,G) && !EQ(B,E))
			{
				if (allEQ3(B,A,F,R) && noneEQ2(B,D, S(sx+2.0, sy+1.0))) { J = K; }
				if (allEQ3(B,C,D,Q) && noneEQ2(B,F, S(sx-2.0, sy+1.0))) { K = J; }
			}
		}

		if (!EQ(F,D))
		{
			if (!EQ(D,I) && !EQ(D,E) && !EQ(D,C))
			{
				if (allEQ3(D,A,H,T) && noneEQ2(D,B, S(sx+1.0, sy+2.0))) { J = L; }
				if (allEQ3(D,G,B,P) && noneEQ2(D,H, S(sx+1.0, sy-2.0))) { L = J; }
			}
			if (!EQ(F,E) && !EQ(F,A) && !EQ(F,G))
			{
				if (allEQ3(F,C,H,T) && noneEQ2(F,B, S(sx-1.0, sy+2.0))) { K = M; }
				if (allEQ3(F,I,B,P) && noneEQ2(F,H, S(sx-1.0, sy-2.0))) { M = K; }
			}
		}
	}

	bool oddX = mod(dst.x, 2.0) > 0.5;
	bool oddY = mod(dst.y, 2.0) > 0.5;

	gl_FragColor = oddY ? (oddX ? M : L) : (oddX ? K : J);
}
