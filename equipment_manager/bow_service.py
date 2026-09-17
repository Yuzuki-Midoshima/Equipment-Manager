"""Bow, Arrow, and String-specific Maya scene operations."""

import math
from typing import Any, Optional, Sequence, Tuple

from .constants import TRANSFORM_CHANNELS
from .maya_utils import (
    apply_transform_offset,
    attribute,
    read_constraint_side,
    require_attribute,
    require_node,
    resolve_side_aliases,
    save_transform_offset,
    side_weights,
)
from .models import ArrowConfig, Side, StringConfig


class BowService:
    """Mutate Arrow and String nodes defined by the rig configuration."""

    POLE_DISTANCE_SCALE = 0.25
    POLE_Y_OFFSET = -200.0

    def __init__(
        self,
        cmds_module: Any,
        arrow_config: ArrowConfig,
        string_config: StringConfig,
    ) -> None:
        self.cmds = cmds_module
        self.arrow = arrow_config
        self.string = string_config

    def switch_arrow_side(
        self, side: Side, follow_enabled: Optional[bool]
    ) -> None:
        self.apply_arrow_offset(side)
        if follow_enabled:
            self.set_arrow_follow(True, side)

    def set_arrow_follow(self, enabled: bool, side: Side) -> None:
        require_node(self.cmds, self.arrow.constraint)
        aliases = self._arrow_aliases()
        if enabled:
            left_alias, right_alias = resolve_side_aliases(aliases)
            left_weight, right_weight = side_weights(side)
            self.cmds.setAttr(
                attribute(self.arrow.constraint, left_alias), left_weight
            )
            self.cmds.setAttr(
                attribute(self.arrow.constraint, right_alias), right_weight
            )
        else:
            for alias in aliases:
                self.cmds.setAttr(attribute(self.arrow.constraint, alias), 0)

    def get_arrow_scene_state(self) -> Tuple[Optional[Side], bool]:
        """Read Arrow side and Follow state from its constraint weights."""
        return read_constraint_side(self.cmds, self.arrow.constraint)

    def save_arrow_offset(self, side: Side) -> None:
        save_transform_offset(
            self.cmds, self.arrow.control, side, TRANSFORM_CHANNELS
        )

    def apply_arrow_offset(self, side: Side) -> None:
        apply_transform_offset(
            self.cmds, self.arrow.control, side, TRANSFORM_CHANNELS
        )

    def save_arrow_pose(self) -> None:
        """Save the visible Arrow pose relative to the Bow control."""
        body = require_node(
            self.cmds, self.arrow.body, context=self.arrow.control
        )
        control = require_node(
            self.cmds, self.arrow.control, context=body
        )
        reset_reference = require_node(
            self.cmds, self.arrow.reset_reference, context=body
        )
        bow_reference = require_node(
            self.cmds, self.arrow.bow_reference, context=control
        )
        arrow_matrix = self.cmds.xform(
            control, q=True, ws=True, matrix=True
        )
        bow_matrix = self.cmds.xform(
            bow_reference, q=True, ws=True, matrix=True
        )
        relative_matrix = self._multiply_matrices(
            arrow_matrix, self._inverse_matrix(bow_matrix)
        )
        self.cmds.xform(
            reset_reference, objectSpace=True, matrix=relative_matrix
        )

    def reset_arrow_pose(self) -> None:
        """Restore the Arrow control relative to the moving bow reference."""
        body = require_node(
            self.cmds, self.arrow.body, context=self.arrow.control
        )
        control = require_node(
            self.cmds, self.arrow.control, context=body
        )
        reset_reference = require_node(
            self.cmds, self.arrow.reset_reference, context=body
        )
        bow_reference = require_node(
            self.cmds, self.arrow.bow_reference, context=control
        )
        relative_matrix = self.cmds.xform(
            reset_reference, q=True, objectSpace=True, matrix=True
        )
        bow_matrix = self.cmds.xform(
            bow_reference, q=True, ws=True, matrix=True
        )
        matrix = self._multiply_matrices(
            relative_matrix, bow_matrix
        )
        self.cmds.xform(control, ws=True, matrix=matrix)
        self.cmds.refresh(force=True)

    @staticmethod
    def _multiply_matrices(left, right):
        """Multiply two flat row-major 4x4 matrices."""
        return [
            sum(
                left[row * 4 + index] * right[index * 4 + column]
                for index in range(4)
            )
            for row in range(4)
            for column in range(4)
        ]

    @staticmethod
    def _inverse_matrix(matrix):
        """Invert a flat 4x4 matrix using Gauss-Jordan elimination."""
        rows = [
            list(matrix[row * 4:(row + 1) * 4])
            + [float(row == column) for column in range(4)]
            for row in range(4)
        ]
        for column in range(4):
            pivot = max(
                range(column, 4), key=lambda row: abs(rows[row][column])
            )
            if abs(rows[pivot][column]) < 1.0e-12:
                raise ValueError("Bow reference matrix is not invertible")
            rows[column], rows[pivot] = rows[pivot], rows[column]
            scale = rows[column][column]
            rows[column] = [value / scale for value in rows[column]]
            for row in range(4):
                if row == column:
                    continue
                factor = rows[row][column]
                rows[row] = [
                    rows[row][index] - factor * rows[column][index]
                    for index in range(8)
                ]
        return [rows[row][column] for row in range(4) for column in range(4, 8)]

    def release_string(self) -> None:
        require_node(self.cmds, self.string.control)
        for name in self.string.draw_attributes:
            if self.cmds.attributeQuery(
                name, node=self.string.control, exists=True
            ):
                self.cmds.setAttr(attribute(self.string.control, name), 0)
        transform_attributes = (
            self.string.translate_attributes + self.string.rotate_attributes
        )
        for name in transform_attributes:
            plug = attribute(self.string.control, name)
            if not self.cmds.connectionInfo(plug, isDestination=True):
                self.cmds.setAttr(plug, 0)

    def set_string_follow(self, enabled: bool, bow_side: Side) -> None:
        if not isinstance(bow_side, Side):
            raise ValueError(
                "Bow side is unknown; select a Bow hand before String Follow"
            )
        arm = "R" if bow_side is Side.LEFT else "L"
        settings = "{}_arm_settings_anim".format(arm)
        hand = "Ik_{}_hand_anim".format(arm)
        settings = require_attribute(
            self.cmds,
            settings,
            "FKIK",
            context=self.string.control,
        )
        if enabled:
            string_control = require_node(self.cmds, self.string.control)
            hand = require_node(
                self.cmds, hand, context=string_control
            )
            if bool(self.cmds.getAttr(attribute(settings, "FKIK"))):
                self.cmds.select(string_control, hand, r=True)
                self.cmds.setToolTo("Move")
                return
            self._match_ik_controls_to_joints(arm, settings)
            # Select the IK hand last so it becomes Maya's active object.
            self.cmds.select(string_control, hand, r=True)
            self.cmds.setToolTo("Move")
        else:
            self._match_fk_controls_to_joints(arm)
            self.cmds.setAttr(attribute(settings, "FKIK"), 0)
            self.cmds.select(clear=True)

    def get_string_follow_enabled(
        self, bow_side: Optional[Side]
    ) -> Optional[bool]:
        """Read the opposite arm FKIK value used by String Follow."""
        if bow_side is None:
            return None
        arm = "R" if bow_side is Side.LEFT else "L"
        settings = "{}_arm_settings_anim".format(arm)
        settings = require_attribute(
            self.cmds,
            settings,
            "FKIK",
            context=self.string.control,
        )
        return bool(self.cmds.getAttr(attribute(settings, "FKIK")))

    def _match_fk_controls_to_joints(self, arm: str) -> None:
        """Match shoulder, elbow, and wrist FK controls before FKIK changes."""
        for joint_template, control_template in self.string.fk_match_pairs:
            joint = joint_template.format(side=arm)
            control = control_template.format(side=arm)
            require_node(self.cmds, joint)
            require_node(self.cmds, control)
            matrix = self.cmds.xform(joint, q=True, ws=True, matrix=True)
            self.cmds.xform(control, ws=True, matrix=matrix)

    def _match_ik_controls_to_joints(
        self, arm: str, settings: str
    ) -> None:
        """Match IK hand and pole controls to the current FK-driven pose."""
        names = {
            "shoulder": self.string.ik_shoulder_joint.format(side=arm),
            "elbow": self.string.ik_elbow_joint.format(side=arm),
            "wrist": self.string.ik_wrist_joint.format(side=arm),
            "hand": self.string.ik_hand_control.format(side=arm),
            "pole": self.string.ik_pole_control.format(side=arm),
        }
        for node in names.values():
            require_node(self.cmds, node)

        shoulder = self._world_position(names["shoulder"])
        elbow = self._world_position(names["elbow"])
        wrist = self._world_position(names["wrist"])
        pole_position = self._calculate_pole_position(
            shoulder,
            elbow,
            wrist,
        )

        # Preserve the hand controller's rig-specific offset by matching it
        # before the mode switch. The pole is applied afterwards because its
        # parent hierarchy is reevaluated when FKIK changes.
        self.cmds.matchTransform(
            names["hand"], names["wrist"], pos=True, rot=True
        )
        self.cmds.setAttr(attribute(settings, "FKIK"), 1)
        self.cmds.xform(names["pole"], ws=True, t=pole_position)

    def _world_position(self, node: str) -> Tuple[float, float, float]:
        values = self.cmds.xform(node, q=True, ws=True, t=True)
        return float(values[0]), float(values[1]), float(values[2])

    @classmethod
    def _calculate_pole_position(
        cls,
        shoulder: Tuple[float, float, float],
        elbow: Tuple[float, float, float],
        wrist: Tuple[float, float, float],
    ) -> Tuple[float, float, float]:
        """Calculate a pole position that remains on the current arm plane."""
        arm_axis = cls._subtract(wrist, shoulder)
        axis_length_sq = cls._dot(arm_axis, arm_axis)
        if axis_length_sq < 1.0e-10:
            raise ValueError("Shoulder and wrist positions overlap")

        shoulder_to_elbow = cls._subtract(elbow, shoulder)
        projection_scale = (
            cls._dot(shoulder_to_elbow, arm_axis) / axis_length_sq
        )
        projection = cls._add(
            shoulder, cls._scale(arm_axis, projection_scale)
        )
        direction = cls._subtract(elbow, projection)
        if cls._length(direction) < 1.0e-5:
            raise ValueError(
                "Cannot calculate pole vector from a straight arm"
            )
        distance = (
            cls._length(shoulder_to_elbow)
            + cls._length(cls._subtract(wrist, elbow))
        ) * cls.POLE_DISTANCE_SCALE
        # Measure the pole distance from the shoulder-to-wrist axis. Starting
        # at the elbow adds the elbow's existing offset a second time and can
        # send the pole control far above the character on strongly bent arms.
        pole = cls._add(
            projection,
            cls._scale(cls._normalize(direction), distance),
        )
        # Bow poses can make the arm-plane normal point steeply upward. Keep
        # the pole at or below the lowest arm joint so it cannot jump above
        # the character while retaining the calculated horizontal direction.
        clamped_y = min(pole[1], shoulder[1], elbow[1], wrist[1])
        return pole[0], clamped_y + cls.POLE_Y_OFFSET, pole[2]

    @staticmethod
    def _add(left, right):
        return tuple(left[index] + right[index] for index in range(3))

    @staticmethod
    def _subtract(left, right):
        return tuple(left[index] - right[index] for index in range(3))

    @staticmethod
    def _scale(vector, scalar):
        return tuple(value * scalar for value in vector)

    @staticmethod
    def _dot(left, right):
        return sum(left[index] * right[index] for index in range(3))

    @classmethod
    def _length(cls, vector):
        return math.sqrt(cls._dot(vector, vector))

    @classmethod
    def _normalize(cls, vector):
        length = cls._length(vector)
        return cls._scale(vector, 1.0 / length)

    def _arrow_aliases(self) -> Sequence[str]:
        aliases = self.cmds.parentConstraint(
            self.arrow.constraint, q=True, wal=True
        ) or []
        resolve_side_aliases(aliases)
        return aliases
