from flask import Flask

from routes import bp

# 入口：创建 Flask app 并注册 Web 层蓝图
app = Flask(__name__)
app.register_blueprint(bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
