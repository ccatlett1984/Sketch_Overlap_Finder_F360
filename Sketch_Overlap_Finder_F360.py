# SketchOverlapFinder - Fusion 360 add-in
# Copyright (C) 2026 ccatlett1984
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, version 3. It is distributed WITHOUT ANY WARRANTY; see
# the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>.
# SPDX-License-Identifier: AGPL-3.0-only

# Finds duplicate and overlapping lines, arcs and circles in a sketch,
# highlights them, lets you step through them, and can optionally clean them up.

import importlib
import math
import os
import traceback

import adsk.core
import adsk.fusion

from .lib import overlap_core as core

importlib.reload(core)   # pick up edits to the core without restarting Fusion

CMD_ID = 'ccatlett1984_SketchOverlapFinder'
CMD_NAME = 'Find Overlapping Curves'
CMD_DESC = ('Find duplicate, fully covered and partially overlapping lines, arcs and '
            'circles in a sketch. Highlights them, zooms to each one, and can remove '
            'exact duplicates and fully covered segments.')

# Sketch contextual tab first, then the solid Inspect panel, then Scripts & Add-ins as a fallback.
PANEL_IDS = ['SketchModifyPanel', 'InspectPanel', 'SolidScriptsAddinsPanel']

COLORS = {
    core.DUPLICATE: (230, 30, 30),     # red
    core.CONTAINED: (255, 140, 0),     # orange
    core.PARTIAL:   (200, 0, 200),     # magenta
}
FOCUS_COLOR = (0, 200, 255)            # cyan
KIND_LABEL = {core.DUPLICATE: 'Duplicate', core.CONTAINED: 'Covered', core.PARTIAL: 'Partial overlap'}
SPLINE_SAMPLES = 25

_app = adsk.core.Application.get()
_ui = _app.userInterface
_handlers = []
_state = {}


def _reset_state():
    _state.clear()
    _state.update(sketch=None, curves=[], prims=[], findings=[], focus=-1, skipped=0, error='')


_reset_state()


# --------------------------------------------------------------------------- helpers

def _design():
    return adsk.fusion.Design.cast(_app.activeProduct)


def _fmt_len(value):
    des = _design()
    if not des:
        return f'{value * 10:.4f} mm'
    um = des.unitsManager
    return um.formatInternalValue(value, um.defaultLengthUnits, True)


def _type_name(curve):
    return curve.objectType.split('::')[-1].replace('Sketch', '')


def _to_prim(curve, tol, include_splines):
    flags = dict(is_ref=curve.isReference, is_constr=curve.isConstruction)

    def flat(*pts):
        return all(abs(p.z) <= tol for p in pts)

    line = adsk.fusion.SketchLine.cast(curve)
    if line:
        p0 = line.startSketchPoint.geometry
        p1 = line.endSketchPoint.geometry
        if not flat(p0, p1):
            return None
        return core.make_line((p0.x, p0.y), (p1.x, p1.y), **flags)

    circle = adsk.fusion.SketchCircle.cast(curve)
    if circle:
        g = circle.geometry
        if not flat(g.center):
            return None
        return core.make_circle((g.center.x, g.center.y), g.radius, **flags)

    arc = adsk.fusion.SketchArc.cast(curve)
    if arc:
        g = arc.geometry
        ev = g.evaluator
        ok, t0, t1 = ev.getParameterExtents()
        ok2, pm = ev.getPointAtParameter((t0 + t1) * 0.5)
        if not (ok and ok2):
            return None
        ps = arc.startSketchPoint.geometry
        pe = arc.endSketchPoint.geometry
        if not flat(g.center, ps, pe, pm):
            return None
        return core.arc_from_points((g.center.x, g.center.y), g.radius,
                                    (ps.x, ps.y), (pm.x, pm.y), (pe.x, pe.y), **flags)

    if not include_splines:
        return None
    # splines, ellipses, elliptical arcs, conics: exact-duplicate check only
    ev = curve.geometry.evaluator
    ok, t0, t1 = ev.getParameterExtents()
    if not ok:
        return None
    params = [t0 + (t1 - t0) * k / (SPLINE_SAMPLES - 1) for k in range(SPLINE_SAMPLES)]
    ok, pts = ev.getPointsAtParameters(params)
    if not ok or not flat(*pts):
        return None
    return core.make_sampled([(p.x, p.y) for p in pts], **flags)


def _score(curve):
    try:
        return curve.geometricConstraints.count + curve.sketchDimensions.count
    except Exception:
        return 0


def _analyze(inputs):
    """Rebuild the findings for the current inputs and refresh the results UI."""
    _state.update(sketch=None, curves=[], prims=[], findings=[], focus=-1, skipped=0, error='')
    sel = inputs.itemById('sketch')
    if sel.selectionCount == 1:
        sketch = adsk.fusion.Sketch.cast(sel.selection(0).entity)
        tol = inputs.itemById('tol').value
        ang = inputs.itemById('angTol').value
        inc_constr = inputs.itemById('incConstr').value
        inc_ref = inputs.itemById('incRef').value
        inc_spl = inputs.itemById('incSplines').value

        if tol <= 0:
            _state['error'] = 'Tolerance must be greater than zero.'
        else:
            curves, prims, skipped = [], [], 0
            for curve in sketch.sketchCurves:
                if curve.isConstruction and not inc_constr:
                    continue
                if curve.isReference and not inc_ref:
                    continue
                try:
                    prim = _to_prim(curve, tol, inc_spl)
                except Exception:
                    prim = None
                if prim is None:
                    skipped += 1
                    continue
                curves.append(curve)
                prims.append(prim)
            _state.update(sketch=sketch, curves=curves, prims=prims, skipped=skipped,
                          findings=core.find_overlaps(prims, tol, ang))

    _refresh_results(inputs)


def _refresh_results(inputs):
    findings = _state['findings']
    curves = _state['curves']
    dd = inputs.itemById('findings')
    dd.listItems.clear()

    if _state['error']:
        inputs.itemById('summary').text = _state['error']
        dd.isEnabled = False
        return
    if _state['sketch'] is None:
        inputs.itemById('summary').text = 'Select a sketch.'
        dd.isEnabled = False
        return

    counts = {k: sum(1 for f in findings if f.kind == k) for k in KIND_LABEL}
    lines = [f'Checked {len(curves)} curves: '
             f'{counts[core.DUPLICATE]} duplicate, {counts[core.CONTAINED]} covered, '
             f'{counts[core.PARTIAL]} partial.']
    if _state['skipped']:
        lines.append(f'{_state["skipped"]} curve(s) not checked (non-planar or excluded type).')
    if not findings:
        lines.append('No overlaps found.')
    inputs.itemById('summary').text = '\n'.join(lines)

    dd.isEnabled = bool(findings)
    dd.listItems.add(f'All ({len(findings)})', True)
    for n, f in enumerate(findings, 1):
        a, b = curves[f.a], curves[f.b]
        dd.listItems.add(f'{n}. {KIND_LABEL[f.kind]}: {_type_name(a)} / {_type_name(b)} - '
                         f'{_fmt_len(f.length)}', False)


def _sketch_matrices(sketch):
    """(matrix for drawing in the native component, matrix to world space)."""
    native = sketch.nativeObject or sketch
    comp_m = native.transform
    world_m = comp_m.copy()
    if sketch.assemblyContext:
        world_m.transformBy(sketch.assemblyContext.transform2)
    return native.parentComponent, comp_m, world_m


def _pt(x, y, m):
    p = adsk.core.Point3D.create(x, y, 0)
    p.transformBy(m)
    return p


def _region_points(region, m):
    kind = region[0]
    if kind == 'line':
        return [_pt(*region[1], m), _pt(*region[2], m)]
    if kind == 'arc':
        (cx, cy), r, s, w = region[1:]
        n = max(2, int(w / (math.pi / 32)) + 1)
        return [_pt(cx + r * math.cos(s + w * k / (n - 1)), cy + r * math.sin(s + w * k / (n - 1)), m)
                for k in range(n)]
    return [_pt(x, y, m) for x, y in region[1]]


def _draw():
    sketch = _state['sketch']
    if not sketch or not _state['findings']:
        return
    comp, comp_m, _ = _sketch_matrices(sketch)
    group = comp.customGraphicsGroups.add()
    focus = _state['focus']

    for n, f in enumerate(_state['findings']):
        is_focus = n == focus
        r, g, b = FOCUS_COLOR if is_focus else COLORS[f.kind]
        effect = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(r, g, b, 255))
        for region in f.regions:
            pts = _region_points(region, comp_m)
            flat = []
            for p in pts:
                flat += [p.x, p.y, p.z]
            coords = adsk.fusion.CustomGraphicsCoordinates.create(flat)
            ent = group.addLines(coords, [], True)
            ent.weight = 7 if is_focus else 4
            ent.color = effect
            ent.depthPriority = 2 if is_focus else 1
            ent.isSelectable = False


def _zoom_to(index):
    sketch = _state['sketch']
    if not sketch or index < 0 or index >= len(_state['findings']):
        return
    _, _, world_m = _sketch_matrices(sketch)
    f = _state['findings'][index]
    pts = []
    for region in f.regions:
        pts += _region_points(region, world_m)
    for i in (f.a, f.b):         # include both curves so you see the context
        x0, y0, x1, y1 = _state['prims'][i].bbox
        pts += [_pt(x0, y0, world_m), _pt(x1, y1, world_m)]
    xs, ys, zs = [p.x for p in pts], [p.y for p in pts], [p.z for p in pts]
    target = adsk.core.Point3D.create((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 0.2)

    vp = _app.activeViewport
    cam = vp.camera
    view_dir = cam.target.vectorTo(cam.eye)
    view_dir.normalize()
    view_dir.scaleBy(cam.eye.distanceTo(cam.target))
    eye = target.copy()
    eye.translateBy(view_dir)
    cam.isFitView = False
    cam.target = target
    cam.eye = eye
    cam.setExtents(size * 1.6, size * 1.6)
    cam.isSmoothTransition = True
    vp.camera = cam


# --------------------------------------------------------------------------- event handlers

class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            _reset_state()
            cmd = args.command
            cmd.isExecutedWhenPreEmpted = False
            cmd.okButtonText = 'Done'
            inputs = cmd.commandInputs
            des = _design()
            units = des.unitsManager.defaultLengthUnits if des else 'mm'

            sel = inputs.addSelectionInput('sketch', 'Sketch', 'Select the sketch to check')
            sel.addSelectionFilter('Sketches')
            sel.setSelectionLimits(1, 1)

            inputs.addValueInput('tol', 'Distance tolerance', units,
                                 adsk.core.ValueInput.createByReal(0.001))   # 0.01 mm
            inputs.addValueInput('angTol', 'Angle tolerance', 'deg',
                                 adsk.core.ValueInput.createByString('0.01 deg'))

            opts = inputs.addGroupCommandInput('opts', 'Include')
            opts.children.addBoolValueInput('incRef', 'Projected / reference curves', True, '', True)
            opts.children.addBoolValueInput('incConstr', 'Construction curves', True, '', False)
            opts.children.addBoolValueInput('incSplines', 'Splines / ellipses (exact duplicates)', True, '', True)

            res = inputs.addGroupCommandInput('results', 'Results')
            res.children.addTextBoxCommandInput('summary', '', 'Select a sketch.', 3, True)
            res.children.addDropDownCommandInput('findings', 'Show',
                                                 adsk.core.DropDownStyles.TextListDropDownStyle)
            res.children.addBoolValueInput('zoom', 'Zoom to selected', True, '', True)

            fix = inputs.addGroupCommandInput('fix', 'On Done')
            fix.children.addBoolValueInput('remDup', 'Delete exact duplicates', True, '', False)
            fix.children.addBoolValueInput('remContained', 'Delete fully covered segments', True, '', False)
            fix.children.addBoolValueInput('selectAfter', 'Select remaining overlapping curves', True, '', True)
            fix.isExpanded = True

            for evt, h in ((cmd.activate, _ActivateHandler()),
                           (cmd.inputChanged, _InputChangedHandler()),
                           (cmd.executePreview, _PreviewHandler()),
                           (cmd.execute, _ExecuteHandler()),
                           (cmd.destroy, _DestroyHandler())):
                evt.add(h)
                _handlers.append(h)
        except Exception:
            _ui.messageBox('SketchOverlapFinder failed:\n{}'.format(traceback.format_exc()))


class _ActivateHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            sketch = adsk.fusion.Sketch.cast(_app.activeEditObject)
            if sketch and inputs.itemById('sketch').selectionCount == 0:
                inputs.itemById('sketch').addSelection(sketch)
            _analyze(inputs)
        except Exception:
            _ui.messageBox('SketchOverlapFinder failed:\n{}'.format(traceback.format_exc()))


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            cid = args.input.id
            if cid in ('sketch', 'tol', 'angTol', 'incConstr', 'incRef', 'incSplines'):
                _analyze(inputs)
            elif cid == 'findings':
                item = inputs.itemById('findings').selectedItem
                _state['focus'] = (item.index - 1) if item else -1
                if _state['focus'] >= 0 and inputs.itemById('zoom').value:
                    _zoom_to(_state['focus'])
        except Exception:
            _ui.messageBox('SketchOverlapFinder failed:\n{}'.format(traceback.format_exc()))


class _PreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _draw()
            args.isValidResult = False     # graphics only; real changes happen on Done
        except Exception:
            _ui.messageBox('SketchOverlapFinder failed:\n{}'.format(traceback.format_exc()))


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            _analyze(inputs)               # fresh objects after the preview rollback
            prims, curves, findings = _state['prims'], _state['curves'], _state['findings']
            if not findings:
                return
            removed = core.plan_removals(findings, prims, [_score(c) for c in curves],
                                         inputs.itemById('remDup').value,
                                         inputs.itemById('remContained').value)
            deleted = 0
            for i in sorted(removed, reverse=True):
                try:
                    if curves[i].deleteMe():
                        deleted += 1
                except Exception:
                    pass

            if inputs.itemById('selectAfter').value:
                keep = {i for f in findings for i in (f.a, f.b)} - removed
                sels = _ui.activeSelections
                sels.clear()
                for i in sorted(keep):
                    try:
                        if curves[i].isValid:
                            sels.add(curves[i])
                    except Exception:
                        pass

            if removed:
                _ui.messageBox(f'Deleted {deleted} curve(s). Use Undo to restore them.',
                               CMD_NAME)
        except Exception:
            _ui.messageBox('SketchOverlapFinder failed:\n{}'.format(traceback.format_exc()))


class _DestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        _reset_state()


# --------------------------------------------------------------------------- add-in entry points

def run(context):
    try:
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if not cmd_def:
            res = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', 'FindOverlaps')
            cmd_def = _ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC, res)
        h = _CreatedHandler()
        cmd_def.commandCreated.add(h)
        _handlers.append(h)

        for pid in PANEL_IDS:
            panel = _ui.allToolbarPanels.itemById(pid)
            if panel and not panel.controls.itemById(CMD_ID):
                ctrl = panel.controls.addCommand(cmd_def)
                if pid == 'SketchModifyPanel':
                    ctrl.isPromotedByDefault = True
    except Exception:
        _ui.messageBox('SketchOverlapFinder failed to start:\n{}'.format(traceback.format_exc()))


def stop(context):
    try:
        for pid in PANEL_IDS:
            panel = _ui.allToolbarPanels.itemById(pid)
            ctrl = panel.controls.itemById(CMD_ID) if panel else None
            if ctrl:
                ctrl.deleteMe()
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        _ui.messageBox('SketchOverlapFinder failed to stop:\n{}'.format(traceback.format_exc()))
