# 定制协作平台

三个人一起做数模论文定制版时，用来记录每一版做到哪一步、由谁负责，文件直接传到服务器。

网址：http://10.16.13.145:8080/dz/ ，校内网或连上校园 VPN 后打开。

服务器的防火墙只放行 22 和 8080，8080 已经被预推免网页占着，所以定制平台跑在本机
8771，由 8080 上那个 `tuimian-web/serve.py` 把 `/dz` 路径原样转过去。

## 怎么用

- 进门只有一个密码框，输 ltr、qyh 或 zjl 都能进。
- 顶上 A 题、B 题、C 题三页加一页汇总。每题一张表，点添加客户加一行，一行是序号、备注、
  定价、文件包和三个勾。
- 文件包能传单个文件也能传整个文件夹，按目录树显示，pdf、图片、txt、tex 这类点名字直接
  在浏览器里看，zip 点查看列出里面的文件，也能逐个看。文件夹整个删。
- 三个勾：定金、结账、完成。点开必须先选一张凭证照片，照片存进这一行的凭证目录，勾旁边
  能点开看；再点一次取消。完成的沉到已完成那一段下面。
- 汇总页按题算客户数、已完成数、定价合计、已结账、未结账、只付了定金的个数。
- 文件存在服务器 `/data1/liutianrui/定制文件/A题/序号/文件名`，序号是这一题里第几个加的，
  一次最多传 500 MB。

## 部署

只用 Python 标准库，服务器上 `python3` 是 3.8。

```
scp server.py index.html liutianrui@10.16.13.145:/data1/liutianrui/dingzhi-sync/
ssh liutianrui@10.16.13.145 bash /data1/liutianrui/dingzhi-sync/start.sh
```

`start.sh` 先杀旧进程再用 nohup 拉起。8080 那边的代理是 `proxy_patch.py` 打进
`tuimian-web/serve.py` 的，改了那边要重跑 `tuimian-web/start.sh`。记录在 `data/records.json`，登录态在 `data/sessions.json`，能进的密码写死在 `server.py` 的 `USERS`。
备份拷 `data` 目录和 `/data1/liutianrui/定制文件`。

服务器 `/data1` 只剩十几 G，磁盘剩余不到 1 GB 时上传会被拒。
