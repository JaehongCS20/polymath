import polymath.mgdfg.serialization.mgdfgv3_pb2 as pb
from polymath.mgdfg.base import Node
from polymath.mgdfg.domain import Domain
from numproto import ndarray_to_proto, proto_to_ndarray
from typing import Iterable, Union
from numbers import Integral


import numpy as np


def pb_store(node, file_path, outname=None):
    if outname:
        file_path = f"{file_path}/{outname}"
    else:
        file_path = f"{file_path}/{node.name}.pb"

    count_before = len(node.nodes.keys())
    with open(file_path, "wb") as program_file:
        program_file.write(_serialize_node(node).SerializeToString())
    count_after = len(node.nodes.keys())

def pb_load(file_path):
    new_program = pb.Node()
    with open(file_path, "rb") as program_file:
        new_program.ParseFromString(program_file.read())
    deser_node = _deserialize_node(new_program)
    return deser_node


def _to_bytes_or_false(val: (Union[str, bytes])) -> Union[bytes, bool]:
    if isinstance(val, bytes):
        return val
    else:
        try:
            return val.encode('utf-8')
        except AttributeError:
            return False

def _serialize_domain(dom, pb_dom):
    for d in dom:
        new_dom = pb_dom.domains.add()
        if isinstance(d, Node):
            new_dom.type = pb.Attribute.Type.NODE
            new_dom.s = _to_bytes_or_false(d.name)
        elif isinstance(d, np.ndarray):
            new_dom.type = pb.Attribute.Type.NDARRAY
            new_dom.nda.CopyFrom(ndarray_to_proto(d))
        elif isinstance(d, int):
            new_dom.type = pb.Attribute.Type.INT32
            new_dom.i32 = d
        elif isinstance(d, float):
            new_dom.type = pb.Attribute.Type.DOUBLE
            new_dom.d = d
        elif isinstance(d, str):
            new_dom.type = pb.Attribute.Type.STRING
            new_dom.s = _to_bytes_or_false(d)
        elif isinstance(d, bool):
            new_dom.type = pb.Attribute.Type.BOOL
            new_dom.b = d
        elif isinstance(d, Iterable):
            if all(isinstance(a, Node) for a in d):
                new_dom.type = pb.Attribute.Type.NODES
                new_dom.ss.extend([_to_bytes_or_false(a.name) for a in d])
            elif all(isinstance(a, list) for a in d):
                new_dom.type = pb.Attribute.Type.NDARRAYS
                np_arr = [ndarray_to_proto(np.asarray(a)) for a in d]
                new_dom.ndas.extend(np_arr)
            elif all(isinstance(a, np.ndarray) for a in d):
                new_dom.type = pb.Attribute.Type.NDARRAYS
                new_dom.ndas.extend(ndarray_to_proto(a) for a in d)
            elif all(isinstance(a, np.integer) for a in d):
                new_dom.type = pb.Attribute.Type.INT32S
                new_dom.i32s.extend(d)
            elif all(isinstance(a, float) for a in d):
                new_dom.type = pb.Attribute.Type.DOUBLES
                new_dom.ds.extend(d)
            elif all(map(lambda bytes_or_false: bytes_or_false is not False, [_to_bytes_or_false(a) for a in d])):
                new_dom.type = pb.Attribute.Type.STRINGS
                new_dom.ss.extend([_to_bytes_or_false(a) for a in d])
            elif all(isinstance(a, bool) for a in d):
                new_dom.type = pb.Attribute.Type.BOOLS
                new_dom.bs.extend(d)
            else:
                raise TypeError(f"Cannot find serializable method for argument {d} with "
                                f"type {type(d)} in domain {dom.names}")

        else:
            raise TypeError(f"Cannot find serializable method for domain {d} with type {type(d)}")

def _deserialize_domain(pb_dom, graph):
    doms = []
    for d in pb_dom.dom.domains:
        if d.type == pb.Attribute.Type.NODE:
            assert d.s.decode("utf-8") in graph.nodes
            arg_node = graph.nodes[d.s.decode("utf-8")]
            doms.append(arg_node)
        elif d.type == pb.Attribute.Type.NDARRAY:
            doms.append(proto_to_ndarray(d.nda))
        elif d.type == pb.Attribute.Type.INT32:
            doms.append(d.i32)
        elif d.type == pb.Attribute.Type.DOUBLE:
            doms.append(d.d)
        elif d.type == pb.Attribute.Type.STRING:
            doms.append(d.s.decode("utf-8"))
        elif d.type == pb.Attribute.Type.BOOL:
            doms.append(d.b)
        elif d.type == pb.Attribute.Type.NODES:
            for a in d.ss:
                assert a.decode("utf-8") in graph.nodes
            arg_node = [graph.nodes[a.decode("utf-8")] for a in d.ss]
            doms.append(arg_node)
        elif d.type == pb.Attribute.Type.NDARRAYS:
            doms.append([proto_to_ndarray(a) for a in d.ndas])
        elif d.type == pb.Attribute.Type.INT32S:
            doms.append(list(d.i32s))
        elif d.type == pb.Attribute.Type.DOUBLES:
            doms.append(list(d.ds))
        elif d.type == pb.Attribute.Type.STRINGS:
            doms.append([a.decode("utf-8") for a in d.ss])
        elif d.type == pb.Attribute.Type.BOOLS:
            doms.append(list(d.b))
        else:
            raise TypeError(f"Cannot find deserializeable method for argument {d} with type {d.type}")
    return Domain(tuple(doms))

def _deserialize_node(pb_node, graph=None):
    set_fields = pb_node.DESCRIPTOR.fields_by_name
    kwargs = {}
    shape_list = []
    for shape in pb_node.shape:
        val_type = shape.WhichOneof("value")
        if val_type == "shape_const":
            shape_list.append(shape.shape_const)
        else:
            shape_list.append(graph.nodes[shape.shape_id])
    kwargs["shape"] = tuple(shape_list)
    kwargs["name"] = pb_node.name
    kwargs["op_name"] = pb_node.op_name

    if pb_node.name == 'x*w':
        print(f"Shape after start: {kwargs['shape']}")
    kwargs["dependencies"] = [dep for dep in pb_node.dependencies]

    args = []
    for arg in pb_node.args:
        if arg.type == pb.Attribute.Type.NODE:
            assert arg.s.decode("utf-8") in graph.nodes
            arg_node = graph.nodes[arg.s.decode("utf-8")]
            args.append(arg_node)
        elif arg.type == pb.Attribute.Type.NDARRAY:
            args.append(proto_to_ndarray(arg.nda))
        elif arg.type == pb.Attribute.Type.INT32:
            args.append(arg.i32)
        elif arg.type == pb.Attribute.Type.DOUBLE:
            args.append(arg.d)
        elif arg.type == pb.Attribute.Type.STRING:
            args.append(arg.s.decode("utf-8"))
        elif arg.type == pb.Attribute.Type.BOOL:
            args.append(arg.b)
        elif arg.type == pb.Attribute.Type.NODES:
            for a in arg.ss:
                assert a.decode("utf-8") in graph.nodes
            arg_node = [graph.nodes[a.decode("utf-8")] for a in arg.ss]
            args.append(arg_node)
        elif arg.type == pb.Attribute.Type.NDARRAYS:
            args.append([proto_to_ndarray(a) for a in arg.ndas])
        elif arg.type == pb.Attribute.Type.INT32S:
            args.append(list(arg.i32s))
        elif arg.type == pb.Attribute.Type.DOUBLES:
            args.append(list(arg.ds))
        elif arg.type == pb.Attribute.Type.STRINGS:
            args.append([a.decode("utf-8") for a in arg.ss])
        elif arg.type == pb.Attribute.Type.BOOLS:
            args.append(list(arg.b))
        else:
            raise TypeError(f"Cannot find deserializeable method for argument {arg} with type {arg.type}")
    args = tuple(args)
    if pb_node.name == 'x*w':
        print(f"Shape after args: {kwargs['shape']}")
    for name in pb_node.kwargs:
        arg = pb_node.kwargs[name]
        if arg.type == pb.Attribute.Type.DOM:
            kwargs[name] = _deserialize_domain(arg, graph)
        elif arg.type == pb.Attribute.Type.NODE:
            assert arg.s.decode("utf-8") in graph.nodes
            arg_node = graph.nodes[arg.s.decode("utf-8")]
            kwargs[name] = arg_node
        elif arg.type == pb.Attribute.Type.NDARRAY:
            kwargs[name] = proto_to_ndarray(arg.nda)
        elif arg.type == pb.Attribute.Type.INT32:
            kwargs[name] = arg.i32
        elif arg.type == pb.Attribute.Type.DOUBLE:
            kwargs[name] = arg.d
        elif arg.type == pb.Attribute.Type.STRING:
            kwargs[name] = arg.s.decode("utf-8")
        elif arg.type == pb.Attribute.Type.BOOL:
            kwargs[name] = arg.b
        elif arg.type == pb.Attribute.Type.NODES:
            for a in arg.ss:
                assert a.decode("utf-8") in graph.nodes
            arg_node = [graph.nodes[a.decode("utf-8")] for a in arg.ss]
            kwargs[name] = arg_node
        elif arg.type == pb.Attribute.Type.NDARRAYS:
            kwargs[name] = [proto_to_ndarray(a) for a in arg.ndas]
        elif arg.type == pb.Attribute.Type.INT32S:
            kwargs[name] = list(arg.i32s)
        elif arg.type == pb.Attribute.Type.DOUBLES:
            kwargs[name] = list(arg.ds)
        elif arg.type == pb.Attribute.Type.STRINGS:
            kwargs[name] = [a.decode("utf-8") for a in arg.ss]
        elif arg.type == pb.Attribute.Type.BOOLS:
            kwargs[name] = list(arg.b)
        else:

            raise TypeError(f"Cannot find deserializeable method for argument {name} with type {arg.type}")
    if pb_node.name == 'x*w':
        print(f"Shape after kwaargs: {kwargs['shape']}\n"
              f"Keys: {kwargs.keys()}")


    mod_name, cls_name = pb_node.module.rsplit(".", 1)
    mod = __import__(mod_name, fromlist=[cls_name])
    if "target" in kwargs:
        func_mod_name, func_name = kwargs["target"].rsplit(".", 1)
        func_mod = __import__(func_mod_name, fromlist=[func_name])
        target = getattr(func_mod, func_name)
        kwargs.pop("target")
        print(f"")
        if cls_name in ["func_op", "slice_op"]:
            node = getattr(mod, cls_name)(target, *args, graph=graph, **kwargs)
        else:
            node = getattr(mod, cls_name)(*args, graph=graph, **kwargs)
    else:

        node = getattr(mod, cls_name)(*args, graph=graph, **kwargs)
    if pb_node.name == 'x*w':
        print(f"Shape at end: {kwargs['shape']}\n"
              f"Node shape: {node.shape}\n"
              f"Args: {args}\n"
              f"Kwargs: {kwargs}\n"
              f"{node}\n")
    for pb_n in pb_node.nodes:
        if pb_n.name in node.nodes:
            continue
        node.nodes[pb_n.name] = _deserialize_node(pb_n, graph=node)
    return node



def _serialize_node(node_instance):
    pb_node = pb.Node(name=node_instance.name, op_name=node_instance.op_name, module=f"{node_instance.__class__.__module__}.{node_instance.__class__.__name__}")
    for shape in node_instance.shape:
        pb_shape = pb_node.shape.add()
        if isinstance(shape, Node):
            pb_shape.shape_id = shape.name
        elif not isinstance(shape, Integral):
            raise TypeError(f"Invalid type for shape {shape} - {type(shape)}")
        else:
            pb_shape.shape_const = shape
    pb_node.dependencies.extend(node_instance.dependencies)

    for arg in node_instance.args:
        new_arg = pb_node.args.add()
        if isinstance(arg, Node):
            new_arg.type = pb.Attribute.Type.NODE
            new_arg.s = _to_bytes_or_false(arg.name)
        elif isinstance(arg, np.ndarray):
            new_arg.type = pb.Attribute.Type.NDARRAY
            new_arg.nda.CopyFrom(ndarray_to_proto(arg))
        elif isinstance(arg, int):
            new_arg.type = pb.Attribute.Type.INT32
            new_arg.i32 = arg
        elif isinstance(arg, float):
            new_arg.type = pb.Attribute.Type.DOUBLE
            new_arg.d = arg
        elif isinstance(arg, str):
            new_arg.type = pb.Attribute.Type.STRING
            new_arg.s = _to_bytes_or_false(arg)
        elif isinstance(arg, bool):
            new_arg.type = pb.Attribute.Type.BOOL
            new_arg.b = arg
        elif isinstance(arg, Iterable):
            if all(isinstance(a, Node) for a in arg):
                new_arg.type = pb.Attribute.Type.NODES
                new_arg.ss.extend([_to_bytes_or_false(a.name) for a in arg])
            elif all(isinstance(a, list) for a in arg):
                new_arg.type = pb.Attribute.Type.NDARRAYS
                np_arr = [ndarray_to_proto(np.asarray(a)) for a in arg]
                new_arg.ndas.extend(np_arr)
            elif all(isinstance(a, np.ndarray) for a in arg):
                new_arg.type = pb.Attribute.Type.NDARRAYS
                new_arg.ndas.extend(ndarray_to_proto(a) for a in arg)
            elif all(isinstance(a, np.integer) for a in arg):
                new_arg.type = pb.Attribute.Type.INT32S
                new_arg.i32s.extend(arg)
            elif all(isinstance(a, float) for a in arg):
                new_arg.type = pb.Attribute.Type.DOUBLES
                new_arg.ds.extend(arg)
            elif all(map(lambda bytes_or_false: bytes_or_false is not False, [_to_bytes_or_false(a) for a in arg])):
                new_arg.type = pb.Attribute.Type.STRINGS
                new_arg.ss.extend([_to_bytes_or_false(a) for a in arg])
            elif all(isinstance(a, bool) for a in arg):
                new_arg.type = pb.Attribute.Type.BOOLS
                new_arg.bs.extend(arg)
            else:
                raise TypeError(f"Cannot find serializable method for argument {arg} with "
                                f"type {type(arg)} in node {node_instance.name} - {node_instance.op_name}")

        else:
            raise TypeError(f"Cannot find serializable method for argument {arg} with type {type(arg)}")

    for name, arg in node_instance.kwargs.items():
        if arg is None:
            continue
        new_arg = pb_node.kwargs[name]
        if isinstance(arg, Domain):
            _serialize_domain(arg, new_arg.dom)
            new_arg.type = pb.Attribute.Type.DOM
        elif isinstance(arg, Node):
            new_arg.type = pb.Attribute.Type.NODE
            new_arg.s = _to_bytes_or_false(arg.name)
        elif isinstance(arg, np.ndarray):
            new_arg.type = pb.Attribute.Type.NDARRAY
            new_arg.nda.CopyFrom(ndarray_to_proto(arg))
        elif isinstance(arg, Integral):
            new_arg.type = pb.Attribute.Type.INT32
            new_arg.i32 = arg
        elif isinstance(arg, float):
            new_arg.type = pb.Attribute.Type.DOUBLE
            new_arg.d = arg
        elif isinstance(arg, str):
            new_arg.type = pb.Attribute.Type.STRING
            new_arg.s = _to_bytes_or_false(arg)
        elif isinstance(arg, bool):
            new_arg.type = pb.Attribute.Type.BOOL
            new_arg.b = _to_bytes_or_false(arg)
        elif isinstance(arg, Iterable):
            if all(isinstance(a, Node) for a in arg):
                new_arg.type = pb.Attribute.Type.NODES
                new_arg.ss.extend([_to_bytes_or_false(a.name) for a in arg])
            elif all(isinstance(a, np.ndarray) for a in arg):
                new_arg.type = pb.Attribute.Type.NDARRAYS
                new_arg.ndas.extend(ndarray_to_proto(a) for a in arg)
            elif all(isinstance(a, Integral) for a in arg):
                new_arg.type = pb.Attribute.Type.INT32S
                new_arg.i32s.extend(arg)
            elif all(isinstance(a, float) for a in arg):
                new_arg.type = pb.Attribute.Type.DOUBLES
                new_arg.ds.extend(arg)
            elif all(map(lambda bytes_or_false: bytes_or_false is not False, [_to_bytes_or_false(a) for a in arg])):
                new_arg.type = pb.Attribute.Type.STRINGS
                new_arg.ss.extend([_to_bytes_or_false(a) for a in arg])
            elif all(isinstance(a, bool) for a in arg):
                new_arg.type = pb.Attribute.Type.BOOLS
                new_arg.bs.extend(arg)
        else:

            raise TypeError(f"Cannot find serializable method for argument {name}={arg} with type {type(arg)} in {node_instance}")

    pb_node.nodes.extend([_serialize_node(node) for _, node in node_instance.nodes.items() if node.name != node_instance.name])

    return pb_node