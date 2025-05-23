
import numpy as np

import bpy
from bpy.props import FloatProperty, EnumProperty, BoolProperty, IntProperty

from sverchok.core.sv_custom_exceptions import SvInvalidInputException
from sverchok.node_tree import SverchCustomTreeNode
from sverchok.data_structure import updateNode, zip_long_repeat, ensure_nesting_level
from sverchok.utils.curve import SvCurve, UnsupportedCurveTypeException
from sverchok.utils.curve.nurbs import SvNurbsCurve
from sverchok.utils.curve.algorithms import concatenate_curves
from sverchok.utils.curve.nurbs_algorithms import concatenate_nurbs_curves

class SvConcatCurvesNode(SverchCustomTreeNode, bpy.types.Node):
        """
        Triggers: Concatenate Curves
        Tooltip: Concatenate several curves into one
        """
        bl_idname = 'SvExConcatCurvesNode'
        bl_label = 'Concatenate Curves'
        bl_icon = 'OUTLINER_OB_EMPTY'
        sv_icon = 'SV_CONCAT_CURVES'

        check : BoolProperty(
            name = "Check coincidence",
            description = "If enabled, then the node will check that the end points of curves being concatenated do actually coincide (within threshold). If they do not, the node will give an error (become red), and the processing will stop",
            default = False,
            update = updateNode)

        max_rho : FloatProperty(
            name = "Max. distance",
            description = "Maximum distance between end points of the curves, which is allowable to decide that they actually coincide",
            min = 0.0,
            default = 0.001,
            precision = 4,
            update = updateNode)

        all_nurbs : BoolProperty(
            name = "All NURBS",
            description = "Convert all input curves to NURBS, and output NURBS - or fail if it is not possible",
            default = False,
            update = updateNode)

        def draw_buttons(self, context, layout):
            layout.prop(self, 'check')
            layout.prop(self, 'all_nurbs')
            if self.check or self.all_nurbs:
                layout.prop(self, 'max_rho')

        def sv_init(self, context):
            self.inputs.new('SvCurveSocket', "Curves")
            self.outputs.new('SvCurveSocket', "Curve")

        def run_check(self, curves):
            for idx, (curve1, curve2) in enumerate(zip(curves, curves[1:])):
                _, t_max_1 = curve1.get_u_bounds()
                t_min_2, _ = curve2.get_u_bounds()
                end1 = curve1.evaluate(t_max_1)
                begin2 = curve2.evaluate(t_min_2)
                distance = np.linalg.norm(begin2 - end1)
                if distance > self.max_rho:
                    self.error("%s - %s", end1, begin2)
                    raise SvInvalidInputException("Distance between the end of {}'th curve and the start of {}'th curve is {} - too much".format(idx, idx+1, distance))

        def to_nurbs(self, curves):
            result = []
            for i,c in enumerate(curves):
                nurbs = SvNurbsCurve.to_nurbs(c)
                if nurbs is None:
                    raise UnsupportedCurveTypeException(f"Curve #{i} - {c} - can not be converted to NURBS!")
                result.append(nurbs)
            return result

        def process(self):
            if not any(socket.is_linked for socket in self.outputs):
                return

            curve_s = self.inputs['Curves'].sv_get()
            if isinstance(curve_s[0], SvCurve):
                curve_s = [curve_s]

            curves_out = []
            for curves in curve_s:
                if self.check:
                    self.run_check(curves)
                if self.all_nurbs:
                    curves = self.to_nurbs(curves)
                if self.all_nurbs:
                    new_curve = concatenate_nurbs_curves(curves, tolerance=self.max_rho)
                else:
                    new_curve = concatenate_curves(curves)
                curves_out.append(new_curve)

            self.outputs['Curve'].sv_set(curves_out)

def register():
    bpy.utils.register_class(SvConcatCurvesNode)

def unregister():
    bpy.utils.unregister_class(SvConcatCurvesNode)

