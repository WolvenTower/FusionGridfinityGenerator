import pytest

from lib.gridfinityUtils.customShape import CustomShape, CustomShapeError


def test_rectangle():
    shape = CustomShape.rectangle(3, 2)
    assert shape.width == 3
    assert shape.length == 2
    assert shape.cell_count == 6


def test_e_shape_multiline():
    shape = CustomShape.parse("""
        ###
        #..
        ###
        #..
        ###
    """)
    assert shape.width == 3
    assert shape.length == 5
    assert shape.cell_count == 11


def test_e_shape_single_line():
    shape = CustomShape.parse('###/#../###/#../###')
    assert shape.cell_count == 11


def test_invalid_character():
    with pytest.raises(CustomShapeError):
        CustomShape.parse('##@/###')


def test_empty_shape():
    with pytest.raises(CustomShapeError):
        CustomShape.parse('.../...')


def test_disconnected_shape():
    with pytest.raises(CustomShapeError):
        CustomShape.parse('#.#')


def test_diagonal_touching_is_not_connected():
    with pytest.raises(CustomShapeError):
        CustomShape.parse('#./.#')


def test_exposed_edges_for_2_by_1_rectangle():
    shape = CustomShape.rectangle(2, 1)
    assert len(shape.exposed_edges()) == 6
