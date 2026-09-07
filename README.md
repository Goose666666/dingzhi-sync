# 定制协作平台

三个人一起做数模论文定制版时，用来记录每一版做到哪一步、由谁负责、文件放在哪。

网页：https://goose666666.github.io/dingzhi-sync/

网页本身是一个静态页，放在公开仓 `dingzhi-sync`；记录和文件都存在私有仓
`dingzhi-sync-data`，网页用每个人自己的 GitHub 令牌读写那个仓，所以三个人看到的是同一份。

## 第一次使用

1. 让仓库主人把你的 GitHub 账号加进 `dingzhi-sync-data` 的协作者，接受邀请。
2. 在 GitHub 上新建一个细粒度令牌：Settings → Developer settings → Personal access
   tokens → Fine-grained tokens → Generate new token。仓库访问只勾 `dingzhi-sync-data`，
   权限里 Contents 选 Read and write，其余不动。复制令牌。
3. 打开网页，点右上角设置，粘贴令牌，署名填你的名字，保存。

令牌只存在你自己浏览器的本地存储里，不会上传。

## 怎么用

- 新建定制：填题目、版本号、画图模板、负责人、状态、侧重点和说明。
- 每一版的卡片上可以改状态、上传文件、编辑、删除。文件按 `files/题目/版本/文件名`
  存进私有仓，单个文件不超过 95 MB。
- 点文件名下载，点删除去掉仓库里的那个文件。
- 页面底部的动态记录谁在什么时候做了什么。

## 冲突

记录存在仓库的 `records.json` 里。两个人同时改时，后保存的一方会先重新读一遍再合并，
按记录合并，不会把对方刚写的整份覆盖掉。同一条记录被两个人同时改，以后保存的为准。
