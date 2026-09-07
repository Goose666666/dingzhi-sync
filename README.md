# 定制协作平台

三个人一起做数模论文定制版时，用来记录每一版做到哪一步、由谁负责，文件直接传到服务器。

网址：http://10.16.13.145:8080/dz/ ，校内网或连上校园 VPN 后打开。

服务器的防火墙只放行 22 和 8080，8080 已经被预推免网页占着，所以定制平台跑在本机
8771，由 8080 上那个 `tuimian-web/serve.py` 把 `/dz` 路径原样转过去。

## 第一次使用

管理员在设置里加成员，给每个人一个名字和初始密码。成员登录后在设置里改自己的密码。

## 怎么用

- 新建定制：填题目、版本号、画图模板、负责人、状态、侧重点和说明。
- 每一版的卡片上可以改状态、上传文件、编辑、删除。文件存在服务器
  `/data1/liutianrui/dingzhi-sync/data/files/记录号/文件名`，一次最多传 500 MB。
- 点文件名下载，点删除去掉服务器上的那个文件。
- 页面底部的动态记录谁在什么时候做了什么。

## 部署

只用 Python 标准库，服务器上 `python3` 是 3.8。

```
scp server.py index.html liutianrui@10.16.13.145:/data1/liutianrui/dingzhi-sync/
ssh liutianrui@10.16.13.145 bash /data1/liutianrui/dingzhi-sync/start.sh
```

`start.sh` 先杀旧进程再用 nohup 拉起。8080 那边的代理是 `proxy_patch.py` 打进
`tuimian-web/serve.py` 的，改了那边要重跑 `tuimian-web/start.sh`。第一次启动会建 admin，密码在 `data/初始密码.txt`。
记录在 `data/records.json`，账号在 `data/users.json`，登录态在 `data/sessions.json`，
备份只需要拷走 `data` 目录。

服务器 `/data1` 只剩十几 G，磁盘剩余不到 1 GB 时上传会被拒。
