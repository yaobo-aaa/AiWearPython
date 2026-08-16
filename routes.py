from flask import Blueprint, request, jsonify

import services

# Web 层：只负责 HTTP 参数解析、缺失校验、响应组装；业务逻辑下沉到 services

bp = Blueprint("api", __name__)


@bp.route("/api/validate-image", methods=["POST"])
def validate_image_api():
    try:
        file = request.files.get("file")
        if file is None or file.filename == "":
            return jsonify({"code": 400, "allow": False, "msg": "缺少 file 参数"}), 400

        image_bytes = file.read()
        result, code = services.validate_image(image_bytes)
        resp = {"code": code}
        resp.update(result)
        return jsonify(resp), code
    except Exception as e:
        return jsonify({"code": 500, "allow": False, "msg": str(e)}), 500


@bp.route("/api/skill/image", methods=["POST"])
def skill_image_api():
    try:
        instruction = request.form.get("instruction")
        if instruction is None or instruction == "":
            return jsonify({"code": 400, "success": False, "url": "", "message": "缺少 instruction 参数"}), 400

        file1 = request.files.get("file1")
        file2 = request.files.get("file2")
        file = request.files.get("file")

        if file1 is not None and file1.filename != "" and file2 is not None and file2.filename != "":
            # 合并模式：file1 + file2
            image_bytes_list = [file1.read(), file2.read()]
        elif file is not None and file.filename != "":
            # 编辑模式：file
            image_bytes_list = [file.read()]
        else:
            return jsonify({"code": 400, "success": False, "url": "", "message": "缺少 file1/file2 或 file 参数"}), 400

        result, code = services.skill_image(instruction, image_bytes_list)
        resp = {
            "code": code,
            "success": result["success"],
            "url": result.get("url", ""),
        }
        if result.get("message"):
            resp["message"] = result["message"]
        return jsonify(resp), code
    except Exception as e:
        return jsonify({"code": 500, "success": False, "url": "", "message": str(e)}), 500


@bp.route("/api/upload-image", methods=["POST"])
def upload_image_api():
    try:
        # 兼容 Java 端两种调用方式：JSON body 或 form 参数
        data = request.get_json(silent=True) or {}
        oss_url = data.get("ossUrl") or request.form.get("ossUrl")
        user_id = data.get("userId") or request.form.get("userId")

        missing = []
        if not oss_url:
            missing.append("ossUrl")
        if not user_id:
            missing.append("userId")
        if missing:
            return jsonify({"success": False, "message": f"缺少 {', '.join(missing)} 参数"}), 400

        result, code = services.upload_image(oss_url, user_id)
        return jsonify(result), code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@bp.route("/api/search-image", methods=["POST"])
def search_image_api():
    """图库检索：文搜图（query）或图搜图（file），返回按相似度降序的 OSS 地址列表。"""
    try:
        user_id = request.form.get("userId")
        if not user_id:
            return jsonify({"code": 400, "message": "缺少 userId 参数", "data": []}), 400

        query = request.form.get("query")
        file = request.files.get("file")
        image_bytes = file.read() if file is not None and file.filename != "" else None

        data, code, message = services.search_image(user_id, query, image_bytes)
        if data is None:
            return jsonify({"code": code, "message": message, "data": []}), code
        return jsonify({"code": code, "message": message, "data": data}), code
    except Exception as e:
        print(f"search-image 处理失败: {e}")
        return jsonify({"code": 500, "message": str(e), "data": []}), 500
