"""验证项目功能目录和模块说明不会在后续修改中退化。"""

from ops.scripts.validate_project_structure import validate


# `test_modular_project_structure_is_complete` 验证结构检查全部通过；参数为无。
def test_modular_project_structure_is_complete():
    result = validate()
    assert result["status"] == "PASS", result["errors"]
    assert result["python_file_count"] >= 99
