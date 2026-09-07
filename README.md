# 定制协作平台

三个人一起做数模论文定制版时，用来记录每一版做到哪一步、由谁负责，文件直接传到服务器。

网址：http://10.16.13.145:8080/dz/ ，校内网或连上校园 VPN 后打开。

服务器的防火墙只放行 22 和 8080，8080 已经被预推免网页占着，所以定制平台跑在本机
8771，由 8080 上那个 `tuimian-web/serve.py` 把 `/dz` 路径原样转过去。

## 怎么用

- 输入自己的名字进入：ltr、qyh、zjl。
- 顶上 A 题、B 题、C 题三页，每页是一张表，一行一个客户的需求，输入客户和需求点添加。
- 每一行能上传文件包、下载、删文件，能编辑客户、需求和负责人。
- 点完成，这一行沉到已完成那一段下面，点恢复再回来。
- 文件存在服务器 `/data1/liutianrui/dingzhi-sync/data/files/行号/文件名`，一次最多传 500 MB。

## 部署

只用 Python 标准库，服务器上 `python3` 是 3.8。

```
scp server.py index.html liutianrui@10.16.13.145:/data1/liutianrui/dingzhi-sync/
ssh liutianrui@10.16.13.145 bash /data1/liutianrui/dingzhi-sync/start.sh
```

`start.sh` 先杀旧进程再用 nohup 拉起。8080 那边的代理是 `proxy_patch.py` 打进
`tuimian-web/serve.py` 的，改了那边要重跑 `tuimian-web/start.sh`。记录在 `data/records.json`，登录态在 `data/sessions.json`，能进的名字写死在 `server.py` 的 `USERS`，
备份只需要拷走 `data` 目录。

服务器 `/data1` 只剩十几 G，磁盘剩余不到 1 GB 时上传会被拒。
