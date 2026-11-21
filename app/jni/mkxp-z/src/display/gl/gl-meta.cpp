/*
** gl-meta.cpp
**
** This file is part of mkxp.
**
** Copyright (C) 2014 Jonas Kulla <Nyocurio@gmail.com>
**
** mkxp is free software: you can redistribute it and/or modify
** it under the terms of the GNU General Public License as published by
** the Free Software Foundation, either version 2 of the License, or
** (at your option) any later version.
**
** mkxp is distributed in the hope that it will be useful,
** but WITHOUT ANY WARRANTY; without even the implied warranty of
** MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
** GNU General Public License for more details.
**
** You should have received a copy of the GNU General Public License
** along with mkxp.  If not, see <http://www.gnu.org/licenses/>.
*/

#include "gl-meta.h"
#include "gl-fun.h"
#include "sharedstate.h"
#include "glstate.h"
#include "quad.h"
#include "shader.h"

#include <SDL_log.h>

/* std::clog never reaches logcat on Android; SDL_Log does. */
#define TJHD_LOG(...) SDL_Log("TJHD: " __VA_ARGS__)

namespace GLMeta
{

void subRectImageUpload(GLint srcW, GLint srcX, GLint srcY,
                        GLint dstX, GLint dstY, GLsizei dstW, GLsizei dstH,
                        SDL_Surface *src, GLenum format)
{
	if (gl.unpack_subimage)
	{
		gl.PixelStorei(GL_UNPACK_ROW_LENGTH, srcW);
		gl.PixelStorei(GL_UNPACK_SKIP_PIXELS, srcX);
		gl.PixelStorei(GL_UNPACK_SKIP_ROWS, srcY);

		TEX::uploadSubImage(dstX, dstY, dstW, dstH, src->pixels, format);
	}
	else
	{
		SDL_PixelFormat *form = src->format;
		SDL_Surface *tmp = SDL_CreateRGBSurface(0, dstW, dstH, form->BitsPerPixel,
		                                        form->Rmask, form->Gmask, form->Bmask, form->Amask);
		SDL_Rect srcRect = { srcX, srcY, dstW, dstH };

		SDL_BlitSurface(src, &srcRect, tmp, 0);

		TEX::uploadSubImage(dstX, dstY, dstW, dstH, tmp->pixels, format);

		SDL_FreeSurface(tmp);
	}
}

void subRectImageEnd()
{
	if (gl.unpack_subimage)
	{
		gl.PixelStorei(GL_UNPACK_ROW_LENGTH, 0);
		gl.PixelStorei(GL_UNPACK_SKIP_PIXELS, 0);
		gl.PixelStorei(GL_UNPACK_SKIP_ROWS, 0);
	}
}

#define HAVE_NATIVE_VAO gl.GenVertexArrays

static void vaoBindRes(VAO &vao)
{
	VBO::bind(vao.vbo);
	IBO::bind(vao.ibo);

	for (size_t i = 0; i < vao.attrCount; ++i)
	{
		const VertexAttribute &va = vao.attr[i];

		gl.EnableVertexAttribArray(va.index);
		gl.VertexAttribPointer(va.index, va.size, va.type, GL_FALSE, vao.vertSize, va.offset);
	}
}

void vaoInit(VAO &vao, bool keepBound)
{
	if (HAVE_NATIVE_VAO)
	{
		gl.GenVertexArrays(1, &vao.nativeVAO);
		gl.BindVertexArray(vao.nativeVAO);
		vaoBindRes(vao);
		if (!keepBound)
			gl.BindVertexArray(0);
	}
	else
	{
		if (keepBound)
		{
			VBO::bind(vao.vbo);
			IBO::bind(vao.ibo);
		}
	}
}

void vaoFini(VAO &vao)
{
	if (HAVE_NATIVE_VAO)
		gl.DeleteVertexArrays(1, &vao.nativeVAO);
}

void vaoBind(VAO &vao)
{
	if (HAVE_NATIVE_VAO)
		gl.BindVertexArray(vao.nativeVAO);
	else
		vaoBindRes(vao);
}

void vaoUnbind(VAO &vao)
{
	if (HAVE_NATIVE_VAO)
	{
		gl.BindVertexArray(0);
	}
	else
	{
		for (size_t i = 0; i < vao.attrCount; ++i)
			gl.DisableVertexAttribArray(vao.attr[i].index);

		VBO::unbind();
		IBO::unbind();
	}
}

#define HAVE_NATIVE_BLIT gl.BlitFramebuffer

static void _blitBegin(FBO::ID fbo, const Vec2i &size)
{
	if (HAVE_NATIVE_BLIT)
	{
		gl.BindFramebuffer(GL_DRAW_FRAMEBUFFER, fbo.gl);
	}
	else
	{
		FBO::bind(fbo);
		glState.viewport.pushSet(IntRect(0, 0, size.x, size.y));

		SimpleShader &shader = shState->shaders().simple;
		shader.bind();
		shader.applyViewportProj();
		shader.setTranslation(Vec2i());
	}
}

void blitBegin(TEXFBO &target)
{
	_blitBegin(target.fbo, Vec2i(target.width, target.height));
}

void blitBeginScreen(const Vec2i &size)
{
	_blitBegin(FBO::ID(0), size);
}

void blitSource(TEXFBO &source)
{
	if (HAVE_NATIVE_BLIT)
	{
		gl.BindFramebuffer(GL_READ_FRAMEBUFFER, source.fbo.gl);
	}
	else
	{
		SimpleShader &shader = shState->shaders().simple;
		shader.setTexSize(Vec2i(source.width, source.height));
		TEX::bind(source.tex);
	}
}

void blitRectangle(const IntRect &src, const Vec2i &dstPos)
{
	blitRectangle(src, IntRect(dstPos.x, dstPos.y, src.w, src.h), false);
}

void blitRectangle(const IntRect &src, const IntRect &dst, bool smooth)
{
	if (HAVE_NATIVE_BLIT)
	{
		gl.BlitFramebuffer(src.x, src.y, src.x+src.w, src.y+src.h,
		                   dst.x, dst.y, dst.x+dst.w, dst.y+dst.h,
		                   GL_COLOR_BUFFER_BIT, smooth ? GL_LINEAR : GL_NEAREST);
	}
	else
	{
		if (smooth)
			TEX::setSmooth(true);

		glState.blend.pushSet(false);
		Quad &quad = shState->gpQuad();
		quad.setTexPosRect(src, dst);
		quad.draw();
		glState.blend.pop();

		if (smooth)
			TEX::setSmooth(false);
	}
}

bool blitRectangleMMPX(TEXFBO &source, const IntRect &src, const IntRect &dst)
{
	MMPXShader &shader = shState->shaders().mmpx;

	if (!shader.valid())
	{
		static bool logged = false;
		if (!logged) { logged = true; TJHD_LOG("mmpx unavailable: shader invalid"); }
		return false;
	}

	/* MMPX maps every source texel onto a 2x2 block; anything else
	 * would sample the wrong neighbours. */
	if (dst.w != src.w * 2 || dst.h != src.h * 2)
	{
		static bool logged = false;
		if (!logged)
		{
			logged = true;
			TJHD_LOG("mmpx rejected: src %dx%d dst %dx%d (needs dst = 2x src)",
			         src.w, src.h, dst.w, dst.h);
		}
		return false;
	}

	glState.blend.pushSet(false);

	shader.bind();

	/* _blitBegin() only pushes a viewport on the non-native path: the native
	 * one copies pixels with glBlitFramebuffer and never samples, so it has
	 * no use for one. MMPX does sample, and applyViewportProj() derives its
	 * ortho matrix from glState.viewport -- without this push it used the
	 * *window* size (1280x720 instead of 1706x960), projected most of the 2x
	 * quad outside the buffer and left the remainder uninitialised. That is
	 * the white-block symptom this fixes.
	 * blitEnd() does not pop on the native path either, so push/pop here
	 * stays balanced. */
	glState.viewport.pushSet(IntRect(0, 0, dst.w, dst.h));
	shader.applyViewportProj();

	/* blitSource() only records a READ framebuffer when native blit is
	 * available, which is enough for a pixel copy but leaves nothing for a
	 * sampler to read: unit 0 would still hold whatever texture the last
	 * draw left there (white, in practice -- hence the blank screen). */
	TEX::bind(source.tex);

	shader.setTranslation(Vec2i());
	shader.setTexSize(Vec2i(src.w, src.h));
	shader.setSourceSize(Vec2i(src.w, src.h));

	Quad &quad = shState->gpQuad();
	quad.setTexPosRect(src, dst);
	quad.draw();

	glState.viewport.pop();

	glState.blend.pop();

	return true;
}

bool blitRectangleSharpBilinear(TEXFBO &source, const IntRect &src,
                                const IntRect &dst, const Vec2i &viewport)
{
	SharpBilinearShader &shader = shState->shaders().sharpBilinear;

	if (!shader.valid())
	{
		static bool logged = false;
		if (!logged) { logged = true; TJHD_LOG("sharpbilinear unavailable: shader invalid"); }
		return false;
	}

	int dstW = dst.w < 0 ? -dst.w : dst.w;
	int dstH = dst.h < 0 ? -dst.h : dst.h;

	if (dstW == 0 || dstH == 0)
		return false;

	glState.blend.pushSet(false);

	shader.bind();

	/* blitBeginScreen() leaves the viewport alone on the native path (it
	 * copies pixels there instead of sampling), so this path has to set it
	 * from the window size before applyViewportProj() reads it back. */
	glState.viewport.pushSet(IntRect(0, 0, viewport.x, viewport.y));
	shader.applyViewportProj();

	TEX::bind(source.tex);

	shader.setTranslation(Vec2i());
	shader.setTexSize(Vec2i(src.w, src.h));
	shader.setSourceSize(Vec2i(src.w, src.h));
	shader.setDestSize(Vec2i(dstW, dstH));

	Quad &quad = shState->gpQuad();
	quad.setTexPosRect(src, dst);
	quad.draw();

	glState.viewport.pop();

	glState.blend.pop();

	return true;
}

void blitEnd()
{
	if (!HAVE_NATIVE_BLIT)
		glState.viewport.pop();
}
}
