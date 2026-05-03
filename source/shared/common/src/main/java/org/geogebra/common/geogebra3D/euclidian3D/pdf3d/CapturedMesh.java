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

import org.geogebra.common.awt.GColor;

/**
 * One drawable's captured mesh: vertices and normals in world coordinates,
 * triangle index list, plus the drawable's color/alpha/curve flag.
 *
 * Vertices come in [x0,y0,z0, x1,y1,z1, ...] flat layout. Normals likewise.
 * Triangles are stored as [v1,v2,v3, normalIdx] quadruples where normalIdx is
 * either an absolute index into the normals array, NORMAL_SAME_INDEX (-1) to
 * use the per-vertex normal, or NORMAL_NOT_SET (-2) to compute from vertices.
 */
final class CapturedMesh {

	/** Use the same index for vertex i as for normal i. */
	static final int NORMAL_SAME_INDEX = -1;
	/** No normal supplied; compute from triangle. */
	static final int NORMAL_NOT_SET = -2;

	final GColor color;
	final double alpha;
	final boolean isCurve;

	final ArrayList<Double> vertices = new ArrayList<>();
	final ArrayList<Double> normals = new ArrayList<>();
	/** packed triples (v1,v2,v3) + normalIdx → quadruples. */
	final ArrayList<Integer> triangles = new ArrayList<>();

	CapturedMesh(GColor color, double alpha, boolean isCurve) {
		this.color = color;
		this.alpha = alpha;
		this.isCurve = isCurve;
	}

	void addVertex(double x, double y, double z) {
		vertices.add(x);
		vertices.add(y);
		vertices.add(z);
	}

	void addNormal(double x, double y, double z) {
		normals.add(x);
		normals.add(y);
		normals.add(z);
	}

	void addTriangle(int v1, int v2, int v3, int normalIdx) {
		triangles.add(v1);
		triangles.add(v2);
		triangles.add(v3);
		triangles.add(normalIdx);
	}

	int triangleCount() {
		return triangles.size() / 4;
	}

	int vertexCount() {
		return vertices.size() / 3;
	}

	int normalCount() {
		return normals.size() / 3;
	}
}
