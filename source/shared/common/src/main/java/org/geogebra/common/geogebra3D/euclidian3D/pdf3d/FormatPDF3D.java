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

import org.geogebra.common.awt.GColor;
import org.geogebra.common.geogebra3D.euclidian3D.printer3D.ExportToPrinter3D;
import org.geogebra.common.geogebra3D.euclidian3D.printer3D.Format;
import org.geogebra.common.kernel.geos.GeoElement;

/**
 * Format that captures every drawable's enumerated geometry into Java
 * CapturedMesh objects instead of writing them out as text. Used by the 3D PDF
 * exporter: after the live view's ExportToPrinter3D walks the scene through
 * this format, the PDF3DProjector projects, sorts, and paints the captured
 * meshes through a 2D vector graphics context.
 *
 * Vertices arrive already multiplied by xInvScale (world units), see
 * ExportToPrinter3D.getVertex; we keep them in those units and project later
 * using the live view's getToScreenMatrix.
 */
public class FormatPDF3D extends Format {

	private final ArrayList<CapturedMesh> meshes = new ArrayList<>();
	private CapturedMesh current;
	private GColor pendingColor;
	private double pendingAlpha = 1.0;
	private boolean pendingIsCurve = false;

	@Override
	public String getExtension() {
		return "pdf";
	}

	@Override
	public void getScriptStart(StringBuilder sb) {
		meshes.clear();
	}

	@Override
	public void getScriptEnd(StringBuilder sb) {
		// nothing to write — output is captured meshes
	}

	@Override
	public void getObjectStart(StringBuilder sb, String type, GeoElement geo,
			boolean transparency, GColor color, double alpha) {
		GColor c = color != null ? color : geo.getObjectColor();
		double a = transparency ? alpha : geo.getAlphaValue();
		if (a <= 0) {
			a = 1.0;
		}
		pendingColor = c;
		pendingAlpha = a;
	}

	@Override
	public void getPolyhedronStart(StringBuilder sb, boolean isFlat,
			boolean isCurve) {
		pendingIsCurve = isCurve;
		current = new CapturedMesh(pendingColor, pendingAlpha, pendingIsCurve);
		meshes.add(current);
	}

	@Override
	public void getPolyhedronEnd(StringBuilder sb) {
		current = null;
	}

	@Override
	public void getVerticesStart(StringBuilder sb, int count) {
		// count is informational; we grow the lists dynamically
	}

	@Override
	public void getVertices(StringBuilder sb, double x, double y, double z) {
		if (current != null) {
			current.addVertex(x, y, z);
		}
	}

	@Override
	public void getVertices(StringBuilder sb, double x, double y, double z,
			double thickness) {
		// fattened-line variant, only used when needsScale() and
		// exportsPointsAndLines together. We don't request thickness, so this
		// shouldn't be called; if it is, ignore the thickness and treat as
		// plain vertex.
		if (current != null) {
			current.addVertex(x, y, z);
		}
	}

	@Override
	public void getVerticesSeparator(StringBuilder sb) {
		// nothing to do
	}

	@Override
	public void getVerticesEnd(StringBuilder sb) {
		// nothing to do
	}

	@Override
	public void getNormalsStart(StringBuilder sb, int count) {
		// nothing to do
	}

	@Override
	public void getNormal(StringBuilder sb, double x, double y, double z,
			boolean withThickness) {
		if (current != null) {
			current.addNormal(x, y, z);
		}
	}

	@Override
	public void getNormalsSeparator(StringBuilder sb) {
		// nothing to do
	}

	@Override
	public void getNormalsEnd(StringBuilder sb) {
		// nothing to do
	}

	@Override
	public void getFacesStart(StringBuilder sb, int count,
			boolean hasSpecificNormals) {
		// nothing to do
	}

	@Override
	public boolean getFaces(StringBuilder sb, int v1, int v2, int v3,
			int normal) {
		if (current != null) {
			int idx;
			if (normal == ExportToPrinter3D.NORMAL_SAME_INDEX) {
				idx = CapturedMesh.NORMAL_SAME_INDEX;
			} else if (normal == ExportToPrinter3D.NORMAL_NOT_SET) {
				idx = CapturedMesh.NORMAL_NOT_SET;
			} else {
				idx = normal;
			}
			current.addTriangle(v1, v2, v3, idx);
		}
		return true;
	}

	@Override
	public void getFacesSeparator(StringBuilder sb) {
		// nothing to do
	}

	@Override
	public void getFacesEnd(StringBuilder sb) {
		// nothing to do
	}

	@Override
	public boolean handlesSurfacesDirectly() {
		return true;
	}

	@Override
	public boolean needsClosedObjectsForCurves() {
		return false;
	}

	@Override
	public boolean needsClosedObjectsForSurfaces() {
		return false;
	}

	@Override
	public boolean needsScale() {
		return false;
	}

	@Override
	public boolean handlesNormals() {
		return true;
	}

	@Override
	public boolean useSpecificViewForExport() {
		// We want to use the LIVE 3D view so the exported PDF matches what the
		// user sees on screen (camera, rotation, zoom).
		return false;
	}

	@Override
	public void setScale(double scale) {
		// not used
	}

	@Override
	protected boolean needsBothSided() {
		return true;
	}

	@Override
	public void setWantsFilledSolids(boolean flag) {
		// not used
	}

	@Override
	public boolean wantsFilledSolids() {
		return false;
	}

	@Override
	public void setExportsPointsAndLines(boolean flag) {
		// not used
	}

	@Override
	public boolean exportsPointsAndLines() {
		return true;
	}

	/** @return captured meshes, in scene traversal order */
	public List<CapturedMesh> getMeshes() {
		return meshes;
	}
}
