import json
import os
import docker
import paramiko
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify,session
import subprocess
import signal
import atexit
import time
import docker
import io
import paramiko
from paramiko import RSAKey, ECDSAKey, Ed25519Key, DSSKey
from functools import wraps
from flask import session, redirect, url_for, jsonify, request
import requests


app = Flask(__name__)
app.secret_key = "sdafadfadf"

# 存储服务器信息的文件 (可以换成数据库)
SERVERS_FILE = 'servers.json'

db = {} # 数据库
flag = {} # session

def get_db():
    with open("db.txt", "a+", encoding="utf-8") as f:
        f.seek(0)
        data = f.readlines()
    if len(data) > 0:
        for i in data:
            tmp = i.strip().split("|")
            db[tmp[0]] = tmp[1:]
    return

def write_db():
    with open("db.txt", "w", encoding="utf-8") as f:
        for k,v in db.items():
            f.write(f'{k}|{v[0]}|{v[1]}|{v[2]}\n')

def check_username(username):
    if username in db:
        return 1
    else:
        return 0


# {"code": 1, "msg": "注册成功"}
# {"code": 0, "msg": "系统错误"}
def create_user(username, password):
    db[username] = [password, str(int(time.time())), "3"]
    write_db()
    return {"code": 1, "msg": "注册成功"}

def authenticate(username, password):
    if db[username][0] == password:
        flag["username"] = username
        return {"code": 1, "msg": "登录成功"}
    else:
        return {"code": 0, "msg": "账号或密码错误！"}


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            # 判断是否为 API 请求（以 /api 开头）
            if request.path.startswith('/api/'):
                return jsonify({'code': 401, 'msg': '未授权，请先登录'}), 401
            else:
                # 页面请求重定向到登录页
                return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# 登录界面
@app.route("/", methods=["GET", "POST"])
def login():
    get_db()
    if request.method == "POST":
        username = request.form.get("username")
        if check_username(username) == 0:
            return json.dumps({"code": 0, "msg": "用户名不存在！"})
        password = request.form.get("password")
        result = authenticate(username, password)   # 改这里
        if result["code"] == 1:
            session["username"] = username
        return json.dumps(result)
    return render_template("login.html")

# @app.route("/register", methods=["POST"])
def register():
    get_db()
    username = request.form.get("username")
    if check_username(username) == 1:
        return json.dumps({"code": 0, "msg": "用户名已存在！"})
    password = request.form.get("password")
    return json.dumps(create_user(username, password))

@app.route("/logout", methods=["POST"])
def logout():
    session.clear() # 把服务器的清掉
    # return render_template("login.html")
    return "<script>alert('退出成功！请重新登录！');window.location.href='/'</script>"


# 读取服务器列表
def load_servers():
    try:
        with open(SERVERS_FILE, 'r') as f:
            servers = json.load(f)
    except FileNotFoundError:
        servers = []
    return servers

# 保存服务器列表
def save_servers(servers):
    with open(SERVERS_FILE, 'w') as f:
        json.dump(servers, f)


def get_server_stats(server):
    ip = server['ip']
    username = server['username']
    port = server['port']
    password = server.get('password')          # 密码（可能不存在）
    private_key_str = server.get('private_key') # 私钥字符串（可能不存在）
    private_key_password = server.get('private_key_password', '')  # 私钥密码（可选）

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': ip,
            'port': port,
            'username': username
        }

        if private_key_str:
            # 尝试加载私钥（支持多种格式）
            pkey = None
            for key_class in [RSAKey, ECDSAKey, Ed25519Key, DSSKey]:
                try:
                    if private_key_password:
                        pkey = key_class.from_private_key(
                            io.StringIO(private_key_str),
                            password=private_key_password
                        )
                    else:
                        pkey = key_class.from_private_key(io.StringIO(private_key_str))
                    break  # 成功加载则退出循环
                except (paramiko.SSHException, Exception):
                    continue  # 尝试下一种密钥类型

            if pkey is None:
                raise Exception("无法解析私钥，请确认私钥格式正确且密码无误")
            connect_kwargs['pkey'] = pkey
        else:
            # 使用密码认证
            if not password:
                raise Exception("未提供密码或私钥，无法连接")
            connect_kwargs['password'] = password

        client.connect(**connect_kwargs)

        # 执行命令获取资源信息
        stdin, stdout, stderr = client.exec_command("top -bn1 | grep 'Cpu(s)'")
        cpu_usage = stdout.read().decode().strip()
        stdin, stdout, stderr = client.exec_command("free -m")
        memory_usage = stdout.read().decode().strip()
        stdin, stdout, stderr = client.exec_command("df -h /")
        disk_usage = stdout.read().decode().strip()
        client.close()

        return {
            'cpu': cpu_usage,
            'memory': memory_usage,
            'disk': disk_usage
        }
    except Exception as e:
        return str(e)


# 首页：运维管理系统主页
@app.route("/index")
@login_required
def index():
    return render_template('index.html')

# 服务器列表页面
@app.route('/servers')
@login_required
def servers():
    servers = load_servers()
    return render_template('servers.html', servers=servers)


@app.route('/add-server', methods=['GET', 'POST'])
@login_required
def add_server():
    if request.method == 'POST':
        ip = request.form['ip']
        username = request.form['username']
        password = request.form.get('password', '')  # 可能为空
        port = int(request.form['port'])

        # 处理私钥文件
        private_key_file = request.files.get('private_key')
        private_key_content = None
        if private_key_file and private_key_file.filename != '':
            private_key_content = private_key_file.read().decode('utf-8')  # 读取文件内容为字符串

        private_key_password = request.form.get('private_key_password', '')

        # 构建服务器条目
        server_entry = {
            'ip': ip,
            'username': username,
            'port': port
        }
        if password:
            server_entry['password'] = password
        if private_key_content:
            server_entry['private_key'] = private_key_content
        if private_key_password:
            server_entry['private_key_password'] = private_key_password

        servers = load_servers()
        servers.append(server_entry)
        save_servers(servers)
        flash(f"服务器 {ip} 添加成功", 'success')
        return redirect(url_for('servers'))

    return render_template('add_server.html')


@app.route('/remove-server/<int:server_id>', methods=['GET', 'POST'])
@login_required
def remove_server(server_id):
    servers = load_servers()
    if request.method == 'POST':
        if 0 <= server_id or server_id < len(servers):
            removed_server = servers.pop(server_id)
            save_servers(servers)
            flash(f"服务器 {removed_server['ip']} 已删除", 'success')  # 发送成功消息
            return redirect(url_for('servers'))
        else:
            flash("服务器不存在", 'error')  # 发送错误消息
            return redirect(url_for('servers'))
    # return render_template('remote_server.html')

# 监控某个服务器的资源利用情况
@app.route('/monitor/<int:server_id>')
@login_required
def monitor(server_id):
    servers = load_servers()
    if server_id < 0 or server_id >= len(servers):
        return "服务器不存在", 404
    server = servers[server_id]
    stats = get_server_stats(server)   # 传递整个字典
    return render_template('monitor.html', server=server, stats=stats)

@app.route('/remote-server')
@login_required
def remote_server():
    return render_template('remote_server.html')

@app.route('/containers')
@login_required
def containers():
    return render_template('containers.html')


# 初始化 Docker 客户端（假设本机有 Docker 环境）
docker_client = docker.from_env()

@app.route('/api/containers')
@login_required
def api_containers():
    try:
        containers = docker_client.containers.list(all=True)
        container_list = [{
            'id': c.id[:12],
            'name': c.name,
            'image': c.image.tags[0] if c.image.tags else c.image.id[:12],
            'status': c.status
        } for c in containers]
        return jsonify(container_list)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/containers/running')
@login_required
def api_containers_running():
    try:
        containers = docker_client.containers.list(filters={'status': 'running'})
        container_list = [{'id': c.id[:12], 'name': c.name, 'image': c.image.tags[0] if c.image.tags else c.image.id[:12], 'status': c.status} for c in containers]
        return jsonify(container_list)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/containers/stopped')
@login_required
def api_containers_stopped():
    try:
        containers = docker_client.containers.list(filters={'status': 'exited'})
        container_list = [{'id': c.id[:12], 'name': c.name, 'image': c.image.tags[0] if c.image.tags else c.image.id[:12], 'status': c.status} for c in containers]
        return jsonify(container_list)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/images')
@login_required
def api_images():
    try:
        images = docker_client.images.list()
        image_list = [{'id': img.id[:12], 'tags': img.tags} for img in images]
        return jsonify(image_list)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/containers/create', methods=['POST'])
@login_required
def api_create_container():
    try:
        data = request.get_json()
        image = data.get('image')
        if not image:
            return jsonify({'error': '镜像名称不能为空'}), 400
        container = docker_client.containers.run(image, detach=True)
        return jsonify({'id': container.id, 'message': '容器创建成功'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/containers/stop/<container_id>', methods=['POST'])
@login_required
def stop_container(container_id):
    try:
        container = docker_client.containers.get(container_id)
        container.stop()
        return jsonify({'message': '容器已停止', 'id': container_id})
    except docker.errors.NotFound:
        return jsonify({'error': '容器不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 本机监控页面（服务列表可在此配置）
@app.route('/self_monitor')
@login_required
def self_monitor():
    # 可根据实际情况修改 IP 地址
    base_ip = 'localhost'
    services = [
        {'name': 'Node Exporter', 'url': f'http://{base_ip}:9100/metrics'},
        {'name': 'cAdvisor',      'url': f'http://{base_ip}:8080/metrics'},
        {'name': 'Prometheus',    'url': f'http://{base_ip}:9090'},
        {'name': 'Grafana',       'url': f'http://{base_ip}:3000'},
        {'name': 'AlertManager',  'url': f'http://{base_ip}:9093'}
    ]
    return render_template('self_monitor.html', services=services)

# 后端检测连通性 API（供前端调用）
@app.route('/api/check_url', methods=['POST'])
@login_required
def check_url():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'error': 'URL missing'}), 400
    try:
        # 先尝试 HEAD 请求（快速），若不支持则降级为 GET（只获取头部）
        resp = requests.head(url, timeout=3, allow_redirects=True)
        if resp.status_code == 405:  # Method Not Allowed
            resp = requests.get(url, timeout=3, stream=True)
        return jsonify({
            'status_code': resp.status_code,
            'ok': resp.ok,
            'url': url
        })
    except requests.exceptions.RequestException as e:
        return jsonify({'error': str(e), 'ok': False, 'url': url}), 500



def start_webssh():
    process = subprocess.Popen([
        'wssh',
        '--address=0.0.0.0',
        '--port=8888',
        '--xheaders=True',
        '--fbidhttp=False'          # 添加此行
    ])
    return process

def cleanup():
    webssh_process.send_signal(signal.SIGTERM)

if __name__ == '__main__':
    # 仅在主进程中启动 WebSSH（避免 reloader 重复启动）
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        webssh_process = start_webssh()
        atexit.register(cleanup)
    app.run(debug=True, host='0.0.0.0')
