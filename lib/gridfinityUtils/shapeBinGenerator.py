"""
Bins with a custom footprint, a shape made of base cells instead of a rectangle.

The feet are the usual ones, one per cell of the shape. The body, the lip and the cavity are drawn from the outline
of the shape (see footprint.py) instead of being boxes, so the walls follow every side of the shape.
"""
import adsk.core, adsk.fusion

from ...lib import fusion360utils as futil
from . import const, combineUtils, commonUtils, extrudeUtils, sketchUtils, baseGenerator, faceUtils, filletUtils, footprint as footprintUtils
from .baseGeneratorInput import BaseGeneratorInput
from .binBodyGeneratorInput import BinBodyGeneratorInput
from .binBodyGenerator import binBodyTopHeight, compartmentCutoutFilletRadius
from .dim import Dim, valueInput
from .footprint import Footprint, Loop

def _sketchPoint(sketch: adsk.fusion.Sketch, x: float, y: float) -> adsk.core.Point3D:
    point = sketch.modelToSketchSpace(adsk.core.Point3D.create(x, y, sketch.origin.z))
    point.z = 0
    return point

def drawLoops(sketch: adsk.fusion.Sketch, loops: list[Loop]):
    """Draws closed chains of lines and arcs, every curve starts on the sketch point the one before it ended on,
    so the sketch gets profiles"""
    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    with sketchUtils.deferSketchCompute(sketch):
        for loop in loops:
            first = None
            previous = None
            for (index, segment) in enumerate(loop):
                isLast = index == len(loop) - 1
                start = previous.endSketchPoint if previous is not None else _sketchPoint(sketch, *segment[1])
                end = first.startSketchPoint if isLast else _sketchPoint(sketch, *segment[-1])
                if segment[0] == 'line':
                    curve = lines.addByTwoPoints(start, end)
                else:
                    curve = arcs.addByThreePoints(start, _sketchPoint(sketch, *segment[2]), end)
                if first is None:
                    first = curve
                previous = curve

def _outerProfile(sketch: adsk.fusion.Sketch) -> adsk.fusion.Profile:
    """The profile made of the outline and the holes in it, the region inside a hole is a profile of its own"""
    return max(list(sketch.profiles), key=lambda profile: profile.profileLoops.count)

def createPrism(
    loops: list[Loop],
    z: Dim | float,
    height: Dim | float,
    direction: adsk.fusion.ExtentDirections,
    targetComponent: adsk.fusion.Component,
    *,
    name: str,
) -> adsk.fusion.ExtrudeFeature:
    """New body from the loops, a sketch on a plane at the given height extruded up or down. Plane, sketch and
    extrude are named after the prism"""
    planeInput: adsk.fusion.ConstructionPlaneInput = targetComponent.constructionPlanes.createInput()
    planeInput.setByOffset(targetComponent.xYConstructionPlane, valueInput(z))
    plane = targetComponent.constructionPlanes.add(planeInput)
    plane.name = f'{name} plane'
    sketch: adsk.fusion.Sketch = targetComponent.sketches.add(plane)
    sketch.name = f'{name} sketch'
    drawLoops(sketch, loops)
    extrude = extrudeUtils.simpleDistanceExtrude(
        _outerProfile(sketch),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        height,
        direction,
        [],
        targetComponent,
        name=name,
    )
    extrude.bodies.item(0).name = name
    return extrude

def _units(input: BinBodyGeneratorInput) -> tuple[float, float]:
    return (input.baseWidth.value, input.baseLength.value)

def bodyOutline(input: BinBodyGeneratorInput, shape: Footprint, inset: float = 0, radius: float | None = None) -> list[Loop]:
    """Outline of the bin body, moved further in by the inset. In the same coordinates as a rectangular bin body,
    which starts at the origin and stands the xy clearance in from the cell borders"""
    (unitX, unitY) = _units(input)
    return footprintUtils.outlineLoops(
        shape,
        unitX,
        unitY,
        input.xyClearance + inset,
        input.binCornerFilletRadius - inset if radius is None else radius,
        -input.xyClearance,
        -input.xyClearance,
    )

def pruneToFootprint(
    bodies: list[adsk.fusion.BRepBody],
    shape: Footprint,
    input: BinBodyGeneratorInput | BaseGeneratorInput,
    targetComponent: adsk.fusion.Component,
    *,
    name: str,
) -> list[adsk.fusion.BRepBody]:
    """Bodies patterned over the whole bounding box of the shape, one for every cell, keep the ones on the cells
    of the shape and remove the rest. Each body is told apart by where its center is"""
    unique: dict[str, adsk.fusion.BRepBody] = {}
    for body in bodies:
        unique[body.entityToken] = body
    kept = []
    for body in unique.values():
        box = body.boundingBox
        column = footprintUtils.cellIndex((box.minPoint.x + box.maxPoint.x) / 2, input.baseWidth.value, input.xyClearance)
        row = footprintUtils.cellIndex((box.minPoint.y + box.maxPoint.y) / 2, input.baseLength.value, input.xyClearance)
        if shape.has(column, row):
            kept.append(body)
        else:
            targetComponent.features.removeFeatures.add(body).name = f'{name} remove'
    return kept

def createFootprintFeet(
    baseInput: BaseGeneratorInput,
    shape: Footprint,
    targetComponent: adsk.fusion.Component,
) -> list[adsk.fusion.BRepBody]:
    """A foot for every cell of the shape, made like the feet of a rectangular bin and with the same options"""
    bodies = baseGenerator.createBaseBodyPattern(baseInput, shape.columns, shape.rows, targetComponent)
    return pruneToFootprint(bodies, shape, baseInput, targetComponent, name='Unused foot')

def _createLipNotchCutters(
    input: BinBodyGeneratorInput,
    shape: Footprint,
    topHeight: Dim,
    targetComponent: adsk.fusion.Component,
) -> list[adsk.fusion.BRepBody]:
    """Base shaped cutters carving the inside of the lip, one for every cell. Same as the lip notch cutters of a
    rectangular bin"""
    features = targetComponent.features
    clearance = input.xyClearance
    cutterInput = BaseGeneratorInput()
    cutterInput.originPoint = adsk.core.Point3D.create(-clearance * 2, -clearance * 2, topHeight.value + const.BIN_BASE_HEIGHT)
    cutterInput.originZ = topHeight + Dim.length(const.BIN_BASE_HEIGHT)
    cutterInput.baseWidth = input.baseWidth + Dim.length(clearance * 2)
    cutterInput.baseLength = input.baseLength + Dim.length(clearance * 2)
    cutterInput.xyClearance = clearance
    cutterInput.hasBottomChamfer = False
    cutterInput.cornerFilletRadius = input.binCornerFilletRadius + clearance * 2
    cutter = baseGenerator.createSingleGridfinityBaseBody(cutterInput, targetComponent, name='Lip notch cutout')

    patternInputBodies = adsk.core.ObjectCollection.create()
    patternInputBodies.add(cutter)
    patternInput = features.rectangularPatternFeatures.createInput(
        patternInputBodies,
        targetComponent.xConstructionAxis,
        adsk.core.ValueInput.createByReal(shape.columns),
        valueInput(input.baseWidth),
        adsk.fusion.PatternDistanceType.SpacingPatternDistanceType,
    )
    patternInput.directionTwoEntity = targetComponent.yConstructionAxis
    patternInput.quantityTwo = adsk.core.ValueInput.createByReal(shape.rows)
    patternInput.distanceTwo = valueInput(input.baseLength)
    pattern = features.rectangularPatternFeatures.add(patternInput)
    pattern.name = 'Lip notch cutouts pattern'
    return pruneToFootprint([cutter] + list(pattern.bodies), shape, input, targetComponent, name='Unused lip notch cutout')

def createShapeLip(
    input: BinBodyGeneratorInput,
    shape: Footprint,
    topHeight: Dim,
    targetComponent: adsk.fusion.Component,
) -> adsk.fusion.BRepBody:
    """The stacking lip along the whole outline, shaped inside like the lip of a rectangular bin with notches"""
    lipHeight = const.BIN_LIP_EXTRA_HEIGHT
    outline = bodyOutline(input, shape)
    lipBody = createPrism(outline, topHeight, lipHeight, adsk.fusion.ExtentDirections.PositiveExtentDirection, targetComponent, name='Lip body').bodies.item(0)

    toSubtract: list[adsk.fusion.BRepBody] = _createLipNotchCutters(input, shape, topHeight, targetComponent)

    # same as the lip middle cutout of a rectangular bin, the wall thickness in from the cell border
    middleCutout = createPrism(
        bodyOutline(input, shape, input.wallThickness - input.xyClearance, input.binCornerFilletRadius - input.wallThickness + input.xyClearance),
        topHeight,
        lipHeight,
        adsk.fusion.ExtentDirections.PositiveExtentDirection,
        targetComponent,
        name='Lip middle cutout',
    )
    toSubtract.append(middleCutout.bodies.item(0))

    if const.BIN_LIP_TOP_RECESS_HEIGHT > const.DEFAULT_FILTER_TOLERANCE:
        recess = createPrism(
            outline,
            topHeight + Dim.length(lipHeight),
            const.BIN_LIP_TOP_RECESS_HEIGHT,
            adsk.fusion.ExtentDirections.NegativeExtentDirection,
            targetComponent,
            name='Lip top chamfer',
        )
        toSubtract.append(recess.bodies.item(0))

    combineUtils.cutBody(lipBody, commonUtils.objectCollectionFromList(toSubtract), targetComponent, name='Lip cutouts cut')
    return lipBody

def createShapeCavity(
    input: BinBodyGeneratorInput,
    shape: Footprint,
    topHeight: Dim,
    targetComponent: adsk.fusion.Component,
) -> adsk.fusion.BRepBody:
    """The space inside the walls, from the body top down to the floor. A single open cavity"""
    wall = input.wallThickness
    depth = topHeight - Dim.length(const.BIN_COMPARTMENT_BOTTOM_THICKNESS)
    # corners keep the wall thickness all the way around, the radius is a wall thickness smaller than the outer one
    radius = compartmentCutoutFilletRadius(input.binCornerFilletRadius - wall)
    cavity = createPrism(
        bodyOutline(input, shape, wall, radius),
        topHeight,
        depth,
        adsk.fusion.ExtentDirections.NegativeExtentDirection,
        targetComponent,
        name='Cavity',
    )
    cavityBody = cavity.bodies.item(0)
    # round the floor of the cavity, an extra, the cavity is fine without it
    try:
        floorEdges = list(faceUtils.getBottomFace(cavityBody).edges)
        filletUtils.createFillet(floorEdges, const.BIN_BODY_CUTOUT_BOTTOM_FILLET_RADIUS, True, targetComponent, name='Cavity floor fillet')
    except Exception as err:
        futil.log(f'Cavity floor fillet skipped: {err}')
    return cavityBody

def createShapeBinBody(
    input: BinBodyGeneratorInput,
    shape: Footprint,
    targetComponent: adsk.fusion.Component,
) -> adsk.fusion.BRepBody:
    """Body of a bin with the footprint of the shape: walls, a single cavity and the lip if asked for, feet not included.
    Fills in the same input as a rectangular bin, the width and length of the bin and its compartments, tabs and
    scoop don't apply"""
    topHeight = binBodyTopHeight(input)
    binExtrude = createPrism(
        bodyOutline(input, shape),
        0,
        topHeight,
        adsk.fusion.ExtentDirections.PositiveExtentDirection,
        targetComponent,
        name='Bin body',
    )
    binBody = binExtrude.bodies.item(0)

    toJoin: list[adsk.fusion.BRepBody] = []
    if input.hasLip:
        toJoin.append(createShapeLip(input, shape, topHeight, targetComponent))
    if not input.isSolid:
        cavityBody = createShapeCavity(input, shape, topHeight, targetComponent)
        combineUtils.cutBody(binBody, commonUtils.objectCollectionFromList([cavityBody]), targetComponent, name='Cavity cut')
    if len(toJoin) > 0:
        combineUtils.joinBodies(binBody, commonUtils.objectCollectionFromList(toJoin), targetComponent, name='Bin body and lip join')
    return binBody

def trimToFootprint(
    bodies: list[adsk.fusion.BRepBody],
    input: BinBodyGeneratorInput,
    shape: Footprint,
    targetComponent: adsk.fusion.Component,
):
    """Cuts away what sticks out of the outline: the feet stand the xy clearance past the body wherever a side of
    the shape has no neighbour cell, and past the rounded corners. Same job as the outer clearance trim of a
    rectangular bin"""
    top = binBodyTopHeight(input).value + (const.BIN_LIP_EXTRA_HEIGHT if input.hasLip else 0)
    bottom = -const.BIN_BASE_HEIGHT - 0.1
    tool = createPrism(
        bodyOutline(input, shape),
        bottom,
        top + 0.1 - bottom,
        adsk.fusion.ExtentDirections.PositiveExtentDirection,
        targetComponent,
        name='Outline trim',
    )
    toolBody = tool.bodies.item(0)
    isSingle = len(bodies) == 1
    for body in bodies:
        combineInput = targetComponent.features.combineFeatures.createInput(body, commonUtils.objectCollectionFromList([toolBody]))
        combineInput.operation = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        combineInput.isKeepToolBodies = not isSingle
        targetComponent.features.combineFeatures.add(combineInput).name = 'Outline trim cut'
    if not isSingle:
        targetComponent.features.removeFeatures.add(toolBody).name = 'Outline trim remove'
