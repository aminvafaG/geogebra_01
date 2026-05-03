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

package org.geogebra.desktop.export;

import java.awt.Dimension;
import java.io.File;
import java.io.FileNotFoundException;

import org.freehep.graphicsio.AbstractVectorGraphicsIO;
import org.freehep.graphicsio.FontConstants;
import org.freehep.graphicsio.pdf.PDFGraphics2D;
import org.freehep.util.UserProperties;
import org.geogebra.common.geogebra3D.euclidian3D.EuclidianView3D;
import org.geogebra.common.geogebra3D.euclidian3D.pdf3d.FormatPDF3D;
import org.geogebra.common.geogebra3D.euclidian3D.pdf3d.PDF3DProjector;
import org.geogebra.common.geogebra3D.euclidian3D.printer3D.ExportToPrinter3D;
import org.geogebra.common.util.debug.Log;
import org.geogebra.desktop.awt.GGraphics2DD;

/**
 * Vector PDF export of the live 3D view.
 *
 * Schedules a runnable on the renderer's next frame, which: captures every
 * drawable's enumerated geometry into FormatPDF3D's CapturedMesh list, then
 * runs PDF3DProjector to project / depth-sort / Lambert-shade / paint the
 * triangles through FreeHEP's PDFGraphics2D into the target file.
 *
 * Limitations of this MVP:
 * - flat per-triangle shading (no smooth shading); curved surfaces will
 *   look faceted at low tesselation
 * - painter's-algorithm sort with no polygon splitting; intersecting
 *   surfaces and cyclic overlap may have visible sort artifacts
 * - no clipping cube clipping; geometry outside the cube still emits
 * - text labels are not yet rendered (drawables emit textured quads which
 *   the geometry enumerator does not surface as text)
 */
public final class Export3DPdf {

	private Export3DPdf() {
		// static-only
	}

	/**
	 * Schedule a vector PDF export of {@code view} into {@code file}.
	 *
	 * The page size is the view's current pixel dimensions multiplied by
	 * {@code exportScale} — i.e. exportScale = 1 produces a PDF at the same
	 * pixel-equivalent size as what's on screen, exportScale = 2 doubles it.
	 *
	 * @param view live 3D view
	 * @param file target file (will be overwritten)
	 * @param exportScale uniform scale for the page size
	 */
	public static void scheduleExport(EuclidianView3D view, File file,
			double exportScale) {
		view.getRenderer().setExport3D(() -> exportNow(view, file, exportScale));
	}

	/**
	 * Run the export immediately (must be called when geometry buffers are
	 * stable — typically from inside a renderer.setExport3D runnable).
	 */
	public static void exportNow(EuclidianView3D view, File file,
			double exportScale) {
		try {
			FormatPDF3D format = new FormatPDF3D();
			ExportToPrinter3D exporter = new ExportToPrinter3D(view,
					view.getRenderer().getGeometryManager());
			exporter.export(format);

			int pageW = (int) Math.max(1,
					Math.round(view.getWidth() * exportScale));
			int pageH = (int) Math.max(1,
					Math.round(view.getHeight() * exportScale));
			Dimension size = new Dimension(pageW, pageH);

			UserProperties props = (UserProperties) PDFGraphics2D
					.getDefaultProperties();
			props.setProperty(PDFGraphics2D.EMBED_FONTS, false);
			props.setProperty(PDFGraphics2D.EMBED_FONTS_AS,
					FontConstants.EMBED_FONTS_TYPE1);
			props.setProperty(AbstractVectorGraphicsIO.TEXT_AS_SHAPES, true);
			PDFGraphics2D.setDefaultProperties(props);

			PDFGraphics2D pdf = new PDFGraphics2D(file, size);
			pdf.setCreator("GeoGebra / FreeHEP Graphics2D Driver (3D vector)");
			pdf.setPageSize(size);
			pdf.startExport();
			try {
				GGraphics2DD g2 = new GGraphics2DD(pdf);
				PDF3DProjector.render(view, format.getMeshes(), g2,
						exportScale);
			} finally {
				pdf.endExport();
			}
		} catch (FileNotFoundException e) {
			Log.error("3D PDF export failed: " + e.getMessage());
		} catch (RuntimeException e) {
			Log.error("3D PDF export failed: " + e.getMessage());
			Log.debug(e);
		}
	}
}
