/*
 * GeoGebra - Dynamic Mathematics for Everyone
 * Copyright (c) GeoGebra GmbH, Altenbergerstr. 69, 4040 Linz, Austria
 * https://www.geogebra.org
 *
 * This file is licensed by GeoGebra GmbH under the EUPL 1.2 licence and
 * may be used under the EUPL 1.2 in compatible projects (see Article 5
 * and the Appendix of EUPL 1.2 for details).
 * You may obtain a copy of the licence at:
 * https://interoperable-europe.ec.europa.eu/collection/eupl/eupl-text-eupl-12
 *
 * Note: The overall GeoGebra software package is free to use for
 * non-commercial purposes only.
 * See https://www.geogebra.org/license for full licensing details
 */

package org.geogebra.common.geogebra3D.euclidian3D.pdf3d;

import java.util.ArrayList;
import java.util.List;

import org.geogebra.common.awt.AwtFactory;
import org.geogebra.common.awt.GColor;
import org.geogebra.common.awt.GGeneralPath;
import org.geogebra.common.awt.GGraphics2D;
import org.geogebra.common.geogebra3D.euclidian3D.EuclidianView3D;
import org.geogebra.common.geogebra3D.euclidian3D.openGL.Renderer;
import org.geogebra.common.kernel.matrix.CoordMatrix4x4;
import org.geogebra.common.kernel.matrix.Coords;

/**
 * Vector PDF rendering of a 3D scene captured into CapturedMesh objects.
 *
 * Shading model matches the live GL fragment+vertex shader as closely as a
 * vector format allows:
 *
 *   • Lambert: factor = max(0, |N · L|), color = (ambient + diffuse * factor) * baseColor.
 *     World-space normals dotted with world-space light position
 *     {@link Renderer#LIGHT_POSITION_D}; ambient/diffuse from
 *     {@link Renderer#AMBIENT_0}. The buffer normals stored by GeoGebra are
 *     world-space; the GL shader dots them with the same world-space light
 *     uniform, so we mirror that.
 *   • Phong specular shine: lightReflect = light - 2(N · light)N; spec =
 *     dot(lightReflect, eyeDir); if spec > 0, color += 0.2 * spec^16. Matches
 *     the FragmentShader.light block.
 *
 * To approximate per-pixel Gouraud shading inside a vector format, triangles
 * with non-uniform per-vertex normals (NORMAL_SAME_INDEX, i.e. smooth-shaded
 * surfaces and curve tubes) get adaptive midpoint subdivision: each triangle
 * recursively splits into four micro-triangles until either depth limit is
 * reached or the per-corner shaded colors are similar enough. Each emitted
 * micro-triangle is flat-shaded by the average of its corner normals — many
 * small flats imitate a smooth gradient. Triangles with one shared normal or
 * NORMAL_NOT_SET are emitted flat without subdivision.
 *
 * Visibility is resolved with the painter's algorithm (sort by farthest depth
 * first). No polygon splitting is done; intersecting surfaces and cyclic
 * overlap may still produce visible sort artifacts. Real per-pixel z-buffer
 * resolution would require either a software rasteriser or PDF
 * compositing-mode tricks neither of which is implemented here.
 */
public class PDF3DProjector {

	/** ambient component (matches Renderer.AMBIENT_0). */
	private static final double AMBIENT = Renderer.AMBIENT_0;
	/** diffuse component (1 - AMBIENT_0, matches Renderer.java line 1500). */
	private static final double DIFFUSE = 1.0 - Renderer.AMBIENT_0;
	/** Phong shine coefficient, matches FragmentShader.light. */
	private static final double SHINE = 0.2;
	/** Phong specular exponent, matches FragmentShader.light. */
	private static final double SHINE_EXP = 16.0;

	/** Max subdivision depth (4^N micro-triangles per smooth-shaded triangle). */
	private static final int MAX_SUBDIV_DEPTH = 3;
	/**
	 * Stop subdividing when the L1 color delta across the triangle is below
	 * this — keeps file size manageable while still smoothing curved areas.
	 * 0..255 scale.
	 */
	private static final double SUBDIV_COLOR_THRESHOLD = 6.0;

	private PDF3DProjector() {
		// static-only entry point
	}

	/**
	 * Render captured meshes into {@code g2} as vector PDF.
	 *
	 * @param view live 3D view (used for to-screen matrix, view size, eye)
	 * @param meshes captured meshes from FormatPDF3D
	 * @param g2 target 2D graphics (typically wraps FreeHEP PDFGraphics2D)
	 * @param exportScale multiplier on the view's pixel size
	 */
	public static void render(EuclidianView3D view, List<CapturedMesh> meshes,
			GGraphics2D g2, double exportScale) {

		final CoordMatrix4x4 toScreen = view.getToScreenMatrix();
		final int viewW = Math.max(1, view.getWidth());
		final int viewH = Math.max(1, view.getHeight());

		// World-space light direction (matches GL uniform).
		final double lx = Renderer.LIGHT_POSITION_D[0];
		final double ly = Renderer.LIGHT_POSITION_D[1];
		final double lz = Renderer.LIGHT_POSITION_D[2];

		// World-space view direction (eye → scene). For orthographic the
		// view's eyePosition stores this direction; for perspective it stores
		// the eye position itself, but FragmentShader uses
		// vec3(eyePosition) for parallel projection, so we mirror that.
		Coords eye = view.getEyePosition();
		final double ex = eye.get(1);
		final double ey = eye.get(2);
		final double ez = eye.get(3);
		final double eLen = Math.max(1e-12,
				Math.sqrt(ex * ex + ey * ey + ez * ez));
		final double evx = ex / eLen;
		final double evy = ey / eLen;
		final double evz = ez / eLen;

		// Lighting context handed down to subdivision.
		LightCtx light = new LightCtx(lx, ly, lz, evx, evy, evz);

		// Project all vertices once per mesh; keep world-space normals.
		ProjectedMesh[] projected = new ProjectedMesh[meshes.size()];
		Coords tmp = new Coords(4);
		for (int m = 0; m < meshes.size(); m++) {
			CapturedMesh cm = meshes.get(m);
			ProjectedMesh pm = new ProjectedMesh(cm.vertexCount(),
					cm.normalCount());
			for (int i = 0; i < cm.vertexCount(); i++) {
				double x = cm.vertices.get(3 * i);
				double y = cm.vertices.get(3 * i + 1);
				double z = cm.vertices.get(3 * i + 2);
				tmp.set(x, y, z, 1);
				Coords r = toScreen.mul(tmp);
				pm.sx[i] = r.get(1);
				pm.sy[i] = r.get(2);
				pm.sz[i] = r.get(3);
			}
			for (int i = 0; i < cm.normalCount(); i++) {
				double nxr = cm.normals.get(3 * i);
				double nyr = cm.normals.get(3 * i + 1);
				double nzr = cm.normals.get(3 * i + 2);
				double l = Math
						.sqrt(nxr * nxr + nyr * nyr + nzr * nzr);
				if (l > 1e-12) {
					pm.nx[i] = nxr / l;
					pm.ny[i] = nyr / l;
					pm.nz[i] = nzr / l;
				}
			}
			projected[m] = pm;
		}

		// Collect every emit-able micro-triangle into one flat list.
		ArrayList<Triangle> tris = new ArrayList<>(8192);
		double[] tmpN = new double[3];
		for (int m = 0; m < meshes.size(); m++) {
			CapturedMesh cm = meshes.get(m);
			ProjectedMesh pm = projected[m];
			GColor base = cm.color != null ? cm.color : GColor.GRAY;
			double baseR = base.getRed() / 255.0;
			double baseG = base.getGreen() / 255.0;
			double baseB = base.getBlue() / 255.0;
			int alpha255 = clamp255(
					(int) Math.round(cm.alpha * 255));
			boolean shineOn = !cm.isCurve;

			for (int i = 0; i < cm.triangleCount(); i++) {
				int v1 = cm.triangles.get(4 * i);
				int v2 = cm.triangles.get(4 * i + 1);
				int v3 = cm.triangles.get(4 * i + 2);
				int normalIdx = cm.triangles.get(4 * i + 3);
				if (v1 < 0 || v2 < 0 || v3 < 0
						|| v1 >= pm.sx.length || v2 >= pm.sx.length
						|| v3 >= pm.sx.length) {
					continue;
				}

				double n1x, n1y, n1z, n2x, n2y, n2z, n3x, n3y, n3z;
				boolean smooth = false;
				if (normalIdx == CapturedMesh.NORMAL_NOT_SET
						|| pm.nx.length == 0) {
					computeFaceNormal(pm, v1, v2, v3, tmpN);
					n1x = n2x = n3x = tmpN[0];
					n1y = n2y = n3y = tmpN[1];
					n1z = n2z = n3z = tmpN[2];
				} else if (normalIdx == CapturedMesh.NORMAL_SAME_INDEX) {
					// Per-vertex normals — smooth-shaded mesh.
					int i1 = clampNormalIdx(v1, pm.nx.length);
					int i2 = clampNormalIdx(v2, pm.nx.length);
					int i3 = clampNormalIdx(v3, pm.nx.length);
					n1x = pm.nx[i1]; n1y = pm.ny[i1]; n1z = pm.nz[i1];
					n2x = pm.nx[i2]; n2y = pm.ny[i2]; n2z = pm.nz[i2];
					n3x = pm.nx[i3]; n3y = pm.ny[i3]; n3z = pm.nz[i3];
					smooth = true;
				} else {
					int ni = normalIdx < pm.nx.length ? normalIdx : 0;
					n1x = n2x = n3x = pm.nx[ni];
					n1y = n2y = n3y = pm.ny[ni];
					n1z = n2z = n3z = pm.nz[ni];
				}

				if (smooth) {
					subdivide(tris,
							pm.sx[v1], pm.sy[v1], pm.sz[v1],
							n1x, n1y, n1z,
							pm.sx[v2], pm.sy[v2], pm.sz[v2],
							n2x, n2y, n2z,
							pm.sx[v3], pm.sy[v3], pm.sz[v3],
							n3x, n3y, n3z,
							baseR, baseG, baseB, alpha255, shineOn, light,
							MAX_SUBDIV_DEPTH);
				} else {
					emitFlat(tris,
							pm.sx[v1], pm.sy[v1], pm.sz[v1],
							pm.sx[v2], pm.sy[v2], pm.sz[v2],
							pm.sx[v3], pm.sy[v3], pm.sz[v3],
							n1x, n1y, n1z,
							baseR, baseG, baseB, alpha255, shineOn, light);
				}
			}
		}

		// Painter's algorithm. The to-screen matrix produces a coord system
		// where smaller Z is farther from the viewer (verified empirically by
		// the GL z-bias logic in VertexShader: gl_Position.z is decreased to
		// pull things forward). So sort ascending = far first = paint first.
		// Stable sort preserves emission order within ties.
		tris.sort((a, c) -> Double.compare(a.depth, c.depth));

		// Convert from to-screen output (origin at viewport center, +Y up) to
		// PDF pixels (origin top-left, +Y down).
		final double halfW = viewW * 0.5;
		final double halfH = viewH * 0.5;
		GGeneralPath path = AwtFactory.getPrototype().newGeneralPath();
		for (Triangle tri : tris) {
			path.reset();
			path.moveTo((tri.x1 + halfW) * exportScale,
					(halfH - tri.y1) * exportScale);
			path.lineTo((tri.x2 + halfW) * exportScale,
					(halfH - tri.y2) * exportScale);
			path.lineTo((tri.x3 + halfW) * exportScale,
					(halfH - tri.y3) * exportScale);
			path.closePath();
			g2.setColor(tri.color);
			g2.fill(path);
		}
	}

	/** Compute the geometric face normal from screen-space vertices. */
	private static void computeFaceNormal(ProjectedMesh pm, int v1, int v2,
			int v3, double[] out) {
		double ax = pm.sx[v2] - pm.sx[v1];
		double ay = pm.sy[v2] - pm.sy[v1];
		double az = pm.sz[v2] - pm.sz[v1];
		double bx = pm.sx[v3] - pm.sx[v1];
		double by = pm.sy[v3] - pm.sy[v1];
		double bz = pm.sz[v3] - pm.sz[v1];
		double cx = ay * bz - az * by;
		double cy = az * bx - ax * bz;
		double cz = ax * by - ay * bx;
		double l = Math.sqrt(cx * cx + cy * cy + cz * cz);
		if (l > 1e-12) {
			out[0] = cx / l;
			out[1] = cy / l;
			out[2] = cz / l;
		} else {
			out[0] = 0;
			out[1] = 0;
			out[2] = 1;
		}
	}

	private static int clampNormalIdx(int v, int n) {
		if (n == 0) {
			return 0;
		}
		return v < n ? v : v % n;
	}

	/**
	 * Compute a Lambert + Phong shaded color (0..255 RGB, packed alpha).
	 *
	 * @param outRgb 3-element scratch (returns r,g,b in 0..255)
	 */
	private static void shade(double nx, double ny, double nz,
			double baseR, double baseG, double baseB, boolean shineOn,
			LightCtx light, double[] outRgb) {
		double lambert = nx * light.lx + ny * light.ly + nz * light.lz;
		// Two-sided lighting: GeoGebra flips the normal for back faces via
		// the `culling` uniform. We don't track culling state here, so use
		// |dot| to keep both sides lit.
		double factor = lambert < 0 ? -lambert : lambert;
		double shade = AMBIENT + DIFFUSE * factor;

		double r = baseR * shade;
		double g = baseG * shade;
		double b = baseB * shade;

		if (shineOn) {
			// reflect(L, N) = L - 2(N · L)N
			double nDotL = nx * light.lx + ny * light.ly + nz * light.lz;
			double rx = light.lx - 2 * nDotL * nx;
			double ry = light.ly - 2 * nDotL * ny;
			double rz = light.lz - 2 * nDotL * nz;
			double spec = rx * light.evx + ry * light.evy + rz * light.evz;
			if (spec > 0) {
				double s2 = spec * spec;
				double s4 = s2 * s2;
				double s8 = s4 * s4;
				double s16 = s8 * s8;
				double add = SHINE * s16;
				r += add;
				g += add;
				b += add;
			}
		}

		outRgb[0] = r * 255;
		outRgb[1] = g * 255;
		outRgb[2] = b * 255;
	}

	private static void emitFlat(ArrayList<Triangle> out,
			double x1, double y1, double z1,
			double x2, double y2, double z2,
			double x3, double y3, double z3,
			double nx, double ny, double nz,
			double baseR, double baseG, double baseB, int alpha255,
			boolean shineOn, LightCtx light) {
		double[] rgb = new double[3];
		shade(nx, ny, nz, baseR, baseG, baseB, shineOn, light, rgb);
		Triangle t = new Triangle();
		t.x1 = x1; t.y1 = y1;
		t.x2 = x2; t.y2 = y2;
		t.x3 = x3; t.y3 = y3;
		t.depth = (z1 + z2 + z3) / 3.0;
		t.color = GColor.newColor(clamp255((int) Math.round(rgb[0])),
				clamp255((int) Math.round(rgb[1])),
				clamp255((int) Math.round(rgb[2])), alpha255);
		out.add(t);
	}

	/**
	 * Recursively split a smooth-shaded triangle until each piece has nearly
	 * uniform shading or the depth limit is hit, then emit each piece flat.
	 * Vertex positions and normals are linearly interpolated; normals are
	 * NOT renormalized between recursion levels — Lambert/Phong are
	 * computed at emit time using the resulting (un-normalized) interpolated
	 * direction, which is acceptable for the ranges of motion seen here.
	 */
	private static void subdivide(ArrayList<Triangle> out,
			double x1, double y1, double z1, double n1x, double n1y, double n1z,
			double x2, double y2, double z2, double n2x, double n2y, double n2z,
			double x3, double y3, double z3, double n3x, double n3y, double n3z,
			double baseR, double baseG, double baseB, int alpha255,
			boolean shineOn, LightCtx light, int depthLeft) {

		if (depthLeft == 0) {
			emitFlat(out, x1, y1, z1, x2, y2, z2, x3, y3, z3,
					(n1x + n2x + n3x) / 3.0,
					(n1y + n2y + n3y) / 3.0,
					(n1z + n2z + n3z) / 3.0,
					baseR, baseG, baseB, alpha255, shineOn, light);
			return;
		}

		double[] c1 = new double[3], c2 = new double[3], c3 = new double[3];
		shade(n1x, n1y, n1z, baseR, baseG, baseB, shineOn, light, c1);
		shade(n2x, n2y, n2z, baseR, baseG, baseB, shineOn, light, c2);
		shade(n3x, n3y, n3z, baseR, baseG, baseB, shineOn, light, c3);

		// Max channel-wise color delta across the three corners.
		double dMax = 0;
		for (int k = 0; k < 3; k++) {
			double d12 = Math.abs(c1[k] - c2[k]);
			double d23 = Math.abs(c2[k] - c3[k]);
			double d31 = Math.abs(c3[k] - c1[k]);
			if (d12 > dMax) dMax = d12;
			if (d23 > dMax) dMax = d23;
			if (d31 > dMax) dMax = d31;
		}
		if (dMax < SUBDIV_COLOR_THRESHOLD) {
			Triangle t = new Triangle();
			t.x1 = x1; t.y1 = y1;
			t.x2 = x2; t.y2 = y2;
			t.x3 = x3; t.y3 = y3;
			t.depth = (z1 + z2 + z3) / 3.0;
			double rAvg = (c1[0] + c2[0] + c3[0]) / 3;
			double gAvg = (c1[1] + c2[1] + c3[1]) / 3;
			double bAvg = (c1[2] + c2[2] + c3[2]) / 3;
			t.color = GColor.newColor(
					clamp255((int) Math.round(rAvg)),
					clamp255((int) Math.round(gAvg)),
					clamp255((int) Math.round(bAvg)), alpha255);
			out.add(t);
			return;
		}

		// Midpoint subdivision: interpolate position and normal at edge mids.
		double x12 = (x1 + x2) * 0.5, y12 = (y1 + y2) * 0.5, z12 = (z1 + z2) * 0.5;
		double x23 = (x2 + x3) * 0.5, y23 = (y2 + y3) * 0.5, z23 = (z2 + z3) * 0.5;
		double x31 = (x3 + x1) * 0.5, y31 = (y3 + y1) * 0.5, z31 = (z3 + z1) * 0.5;

		double n12x = (n1x + n2x) * 0.5, n12y = (n1y + n2y) * 0.5, n12z = (n1z + n2z) * 0.5;
		double n23x = (n2x + n3x) * 0.5, n23y = (n2y + n3y) * 0.5, n23z = (n2z + n3z) * 0.5;
		double n31x = (n3x + n1x) * 0.5, n31y = (n3y + n1y) * 0.5, n31z = (n3z + n1z) * 0.5;

		int dl = depthLeft - 1;
		subdivide(out, x1, y1, z1, n1x, n1y, n1z,
				x12, y12, z12, n12x, n12y, n12z,
				x31, y31, z31, n31x, n31y, n31z,
				baseR, baseG, baseB, alpha255, shineOn, light, dl);
		subdivide(out, x12, y12, z12, n12x, n12y, n12z,
				x2, y2, z2, n2x, n2y, n2z,
				x23, y23, z23, n23x, n23y, n23z,
				baseR, baseG, baseB, alpha255, shineOn, light, dl);
		subdivide(out, x31, y31, z31, n31x, n31y, n31z,
				x23, y23, z23, n23x, n23y, n23z,
				x3, y3, z3, n3x, n3y, n3z,
				baseR, baseG, baseB, alpha255, shineOn, light, dl);
		subdivide(out, x12, y12, z12, n12x, n12y, n12z,
				x23, y23, z23, n23x, n23y, n23z,
				x31, y31, z31, n31x, n31y, n31z,
				baseR, baseG, baseB, alpha255, shineOn, light, dl);
	}

	private static int clamp255(int v) {
		return v < 0 ? 0 : (v > 255 ? 255 : v);
	}

	private static final class ProjectedMesh {
		final double[] sx;
		final double[] sy;
		final double[] sz;
		final double[] nx;
		final double[] ny;
		final double[] nz;

		ProjectedMesh(int vc, int nc) {
			sx = new double[vc];
			sy = new double[vc];
			sz = new double[vc];
			nx = new double[nc];
			ny = new double[nc];
			nz = new double[nc];
		}
	}

	private static final class Triangle {
		double x1, y1, x2, y2, x3, y3;
		double depth;
		GColor color;
	}

	private static final class LightCtx {
		final double lx, ly, lz;
		final double evx, evy, evz;

		LightCtx(double lx, double ly, double lz,
				double evx, double evy, double evz) {
			this.lx = lx;
			this.ly = ly;
			this.lz = lz;
			this.evx = evx;
			this.evy = evy;
			this.evz = evz;
		}
	}
}
