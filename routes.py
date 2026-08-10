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

        file = request.files.get("file")
        if file is None or file.filename == "":
            return jsonify({"code": 400, "success": False, "url": "", "message": "缺少 file 参数"}), 400

        result, code = services.skill_image(instruction, file.read())
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
