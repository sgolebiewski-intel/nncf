"""
 Copyright (c) 2022 Intel Corporation
 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
      http://www.apache.org/licenses/LICENSE-2.0
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
"""

from collections import Counter
from copy import deepcopy
import onnx
from onnx.version_converter import convert_version, ConvertError  # pylint: disable=no-name-in-module
from nncf.common.utils.logger import logger as nncf_logger


class ONNXModelNormalizer:
    """
    The class, which helps to prepare the ONNX model for work with Post-Training Algorithms.
    Implements methods for adding necessary information to the ONNX model.
    """
    TARGET_OPSET_VERSION = 13
    TARGET_IR_VERSION = 7

    @staticmethod
    def infer_models_shape(model: onnx.ModelProto) -> onnx.ModelProto:
        """
        Infers 'model' and saves the edges shape into the 'model'.
        :param model: ONNX model, which is inferred.
        :return: ONNX model with inferred shapes.
        """
        # ONNX shape inference
        # https://github.com/onnx/onnx/blob/main/docs/proposals/SymbolicShapeInfProposal.md
        inferred_shape_model = onnx.shape_inference.infer_shapes(model)
        return inferred_shape_model

    @staticmethod
    def convert_opset_version(model: onnx.ModelProto, opset_version: int) -> onnx.ModelProto:
        """
        Tries to convert 'model' Opset Version to 'opset_version'.
        If the 'model' can not be converted returns the original 'model'.
        :param model: ONNX model to convert.
        :param opset_version: target Opset Version.
        :return: Converted ONNX model or Original ONNX model.
        """
        # pylint: disable=no-member
        try:
            modified_model = convert_version(model, opset_version)
            onnx.checker.check_model(modified_model)
            nncf_logger.info(
                'The model was successfully converted  to the Opset Version = {}'.format(
                    modified_model.opset_import[0].version))
            return modified_model
        except (RuntimeError, ConvertError):
            nncf_logger.error(
                f"Couldn't convert target model to the Opset Version {opset_version}. "
                f"Using the copy of the original model")
            return model

    @staticmethod
    def convert_ir_version(model: onnx.ModelProto, ir_version: int) -> onnx.ModelProto:
        """
        Creates a new model from the 'model' graph with the target IR Version.
        :param model: ONNX model to convert.
        :param ir_version: Target IR Version.
        :return: Converted ONNX model.
        """
        op = onnx.OperatorSetIdProto()
        op.version = model.opset_import[0].version
        modified_model = onnx.helper.make_model(model.graph, ir_version=ir_version, opset_imports=[op])
        onnx.checker.check_model(modified_model)
        nncf_logger.info(
            'The model was successfully converted  to the IR Version = {}'.format(
                modified_model.ir_version))
        return modified_model

    @staticmethod
    def replace_empty_node_name(model: onnx.ModelProto) -> onnx.ModelProto:
        """
        Sets a unique name to every node in 'model' with empty name field.
        NNCFGraph expects every node to have a unique name.
        :param model: ONNX model.
        :return: ONNX model with filled nodes.
        """
        for i, node in enumerate(model.graph.node):
            if node.name == '':
                node.name = node.op_type + '_nncf_' + str(i)

        name_counter = Counter([node.name for node in model.graph.node])

        if max(name_counter.values()) > 1:
            raise RuntimeError(
                f"Nodes {[(name, cnt) for name, cnt in name_counter.items() if cnt > 1]} "
                "(name, counts) occurred more than once. "
                "NNCF expects every node to have a unique name.")

        return model

    @staticmethod
    def normalize_model(model: onnx.ModelProto, convert_opset_version: bool = True) -> onnx.ModelProto:
        """
        Makes a deepcopy of the 'model' and do processing steps:
        1) Convert Opset Version to TARGET_OPSET_VERSION.
        2) Convert IR Version to TARGET_IR_VERSION.
        3) Infers shapes of the 'model' tensors.
        4) Adds shape of 'model' Initializers.
        5) Replace empty node names.
        :param model: ONNX model to process.
        :param convert_opset_version: Whether convert Opset and IR Versions.
        :return: new ONNX model, prepared for quantization.
        """
        nncf_logger.info('Preparing the model for the Post-Training Algorithms.')
        modified_model = deepcopy(model)
        onnx.checker.check_model(modified_model)
        if convert_opset_version:
            model_opset = modified_model.opset_import[0].version
            model_ir_version = modified_model.ir_version
            nncf_logger.debug('Original Opset Version = {}'.format(model_opset))
            nncf_logger.debug('Original IR Version = {}'.format(model_ir_version))
            if model_opset >= ONNXModelNormalizer.TARGET_OPSET_VERSION and \
                    model_ir_version >= ONNXModelNormalizer.TARGET_IR_VERSION:
                nncf_logger.info(
                    f"The model Opset Version {model_opset} and IR Version {model_ir_version} are equal or higher."
                    f" Using the copy of the original model")
            else:
                if model_opset < ONNXModelNormalizer.TARGET_OPSET_VERSION:
                    modified_model = ONNXModelNormalizer.convert_opset_version(modified_model,
                                                                               ONNXModelNormalizer.TARGET_OPSET_VERSION)
                if model_ir_version < ONNXModelNormalizer.TARGET_IR_VERSION:
                    modified_model = ONNXModelNormalizer.convert_ir_version(modified_model,
                                                                            ONNXModelNormalizer.TARGET_IR_VERSION)
        modified_model = ONNXModelNormalizer.infer_models_shape(modified_model)
        modified_model = ONNXModelNormalizer.replace_empty_node_name(modified_model)
        nncf_logger.info('The model was successfully processed.')
        return modified_model