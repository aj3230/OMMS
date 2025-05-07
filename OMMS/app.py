import json

import docker
import paramiko
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import subprocess
import signal
import atexit

# from paramiko import client
import paramiko  # 正确导入整个库
import docker
# 或
# from paramiko import SSHClient  # 直接导入 SSHClient 类

app = Flask(__name__)
app.secret_key = 'lalala'

# 存储服务器信息的文件 (可以换成数据库)
SERVERS_FILE = 'servers.json'


# 启动 WebSSH 服务
def start_webssh():
    process = subprocess.Popen(['wssh', '--address=127.0.0.1', '--port=8888', '--xheaders=True'])
    return process

webssh_process = start_webssh()

# 注册退出处理函数，确保 Flask 关闭时也关闭 WebSSH
def cleanup():
    webssh_process.send_signal(signal.SIGTERM)

atexit.register(cleanup)

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
def get_server_stats(ip, username, password, port):
    try:
        client = paramiko.SSHClient() # 创建 SSH 客户端
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy()) # 自动接受未知主机密钥（首次连接时需手动确认）
        client.connect(ip, port=port, username=username, password=password) # 建立连接

        # 获取 CPU 使用情况
        stdin, stdout, stderr = client.exec_command("top -bn1 | grep 'Cpu(s)'")
        cpu_usage = stdout.read().decode().strip()

        # 获取内存使用情况
        stdin, stdout, stderr = client.exec_command("free -m")
        memory_usage = stdout.read().decode().strip()

        # 获取磁盘使用情况
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
@app.route('/')
def index():
    return render_template('index.html')

# 服务器列表页面
@app.route('/servers')
def servers():
    servers = load_servers()
    return render_template('servers.html', servers=servers)

# 添加服务器的路由
@app.route('/add-server', methods=['GET', 'POST'])
def add_server():
    if request.method == 'POST':
        ip = request.form['ip']
        username = request.form['username']
        password = request.form['password']
        port = request.form['port']

        # 加载现有的服务器列表
        servers = load_servers()
        servers.append({'ip': ip, 'username': username, 'password': password, 'port': int(port)})

        # 保存服务器列表
        save_servers(servers)

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
    stats = get_server_stats(server['ip'], server['username'], server['password'], server['port'])

    return render_template('monitor.html', server=server, stats=stats)

@app.route('/remote-server')
def remote_server():
    return render_template('remote_server.html')

@app.route('/containers')
def containers():
    return render_template('containers.html')

#
# client = docker.from_env()
# # 新增容器管理路由
# @app.route('/get_containers', methods=['GET'])
# def get_containers():
#     try:
#         containers = client.containers.list(all=True)
#
#         return jsonify([{
#             'id': c.id,
#             'name': c.name,
#             'image': c.image.tags[0],
#             'status': c.status,
#             'ports': c.attrs['NetworkSettings']['Ports']
#         } for c in containers])
#     except docker.errors.APIError as e:
#         return jsonify({'error': str(e)}), 500
#
# @app.route('/create_container', methods=['POST'])
# def create_container():
#     data = request.get_json()
#     try:
#         container = client.containers.run(
#             image=data['image'],
#             name=data.get('name', ''),
#             ports=data.get('ports', {}),
#             volumes=data.get('volumes', {}),
#             detach=True,
#             security_opt=['apparmor:unconfined']
#         )
#         return jsonify({'id': container.id}), 201
#     except docker.errors.APIError as e:
#         return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)