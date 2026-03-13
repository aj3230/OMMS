import json
import os

import docker
import paramiko
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify,session
import subprocess
import signal
import atexit
import time
app = Flask(__name__)
app.secret_key = "sdafadfadf"
# ???

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

@app.route("/register", methods=["POST"])
def register():
    get_db()
    username = request.form.get("username")
    if check_username(username) == 1:
        return json.dumps({"code": 0, "msg": "用户名已存在！"})
    password = request.form.get("password")
    return json.dumps(create_user(username, password))

# 取消了“用户名实时检查功能”
# @app.route("/checkusername", methods=["POST"])
# def checkusername():
#     username = request.form.get("username")
#     get_db()
#     if check_username(username):
#         return json.dumps({"code": 1})
#     return json.dumps({"code": 0})

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

# 执行远程命令获取服务器资源信息
# def get_server_stats(ip, username, password, port):
#     try:
#         client = paramiko.SSHClient() # 创建 SSH 客户端
#         client.set_missing_host_key_policy(paramiko.AutoAddPolicy()) # 自动接受未知主机密钥（首次连接时需手动确认）
#         client.connect(ip, port=port, username=username, password=password) # 建立连接
#
#         # 获取 CPU 使用情况
#         stdin, stdout, stderr = client.exec_command("top -bn1 | grep 'Cpu(s)'")
#         cpu_usage = stdout.read().decode().strip()
#
#         # 获取内存使用情况
#         stdin, stdout, stderr = client.exec_command("free -m")
#         memory_usage = stdout.read().decode().strip()
#
#         # 获取磁盘使用情况
#         stdin, stdout, stderr = client.exec_command("df -h /")
#         disk_usage = stdout.read().decode().strip()
#
#         client.close()
#
#         return {
#             'cpu': cpu_usage,
#             'memory': memory_usage,
#             'disk': disk_usage
#         }
#
#     except Exception as e:
#         return str(e)

import io
import paramiko
from paramiko import RSAKey, ECDSAKey, Ed25519Key, DSSKey


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
def index():
    return render_template('index.html')

# 服务器列表页面
@app.route('/servers')
def servers():
    servers = load_servers()
    return render_template('servers.html', servers=servers)

# 添加服务器的路由
# @app.route('/add-server', methods=['GET', 'POST'])
# def add_server():
#     if request.method == 'POST':
#         ip = request.form['ip']
#         username = request.form['username']
#         password = request.form['password']
#         port = request.form['port']
#
#         # 加载现有的服务器列表
#         servers = load_servers()
#         servers.append({'ip': ip, 'username': username, 'password': password, 'port': int(port)})
#
#         # 保存服务器列表
#         save_servers(servers)
#
#         return redirect(url_for('servers'))
#
#     return render_template('add_server.html')

@app.route('/add-server', methods=['GET', 'POST'])
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
def monitor(server_id):
    servers = load_servers()
    if server_id < 0 or server_id >= len(servers):
        return "服务器不存在", 404
    server = servers[server_id]
    stats = get_server_stats(server)   # 传递整个字典
    return render_template('monitor.html', server=server, stats=stats)
# def monitor(server_id):
#     servers = load_servers()
#     if server_id < 0 or server_id >= len(servers):
#         return "服务器不存在", 404
#
#     server = servers[server_id]
#     stats = get_server_stats(server['ip'], server['username'], server['password'], server['port'])
#
#     return render_template('monitor.html', server=server, stats=stats)

@app.route('/remote-server')
def remote_server():
    return render_template('remote_server.html')

@app.route('/containers')
def containers():
    return render_template('containers.html')

@app.route('/servers')
def get_containers_status(ip, username, password, port):
    try:
        client = paramiko.SSHClient() # 创建 SSH 客户端
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy()) # 自动接受未知主机密钥（首次连接时需手动确认）
        client.connect(ip, port=port, username=username, password=password) # 建立连接

        # 获取 容器 状态
        stdin, stdout, stderr = client.exec_command("docker ps -a'")
        contaniner_status = stdout.read().decode().strip()

        client.close()

        return {
            'contaniner_status': contaniner_status
        }

    except Exception as e:
        return str(e)


# Flask 应用与 WebSSH 服务的启动和关闭状态同步
def start_webssh():
    process = subprocess.Popen(['wssh', '--address=127.0.0.1', '--port=8888', '--xheaders=True'])
    return process

def cleanup():
    webssh_process.send_signal(signal.SIGTERM)


# Flask 应用与 WebSSH 服务的启动和关闭状态同步
## 启动 WebSSH 服务
webssh_process = start_webssh()
## 注册退出处理函数，确保 Flask 关闭时也关闭 WebSSH
atexit.register(cleanup)


if __name__ == '__main__':
    app.run(debug=True)