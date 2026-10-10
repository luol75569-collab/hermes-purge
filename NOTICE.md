# 来源与署名

本项目参考并移植 [YuJunZhiXue/dsh-purge](https://github.com/YuJunZhiXue/dsh-purge) 的思路与实现方式。Hermes 侧代码独立编写，未复制原仓库的代码文件、图片或演练台素材。

- 原作者：小杨 / YuJunZhiXue
- 来源仓库：https://github.com/YuJunZhiXue/dsh-purge
- 参考提交：164e15106d8e243eb0111e04181aeca2b6020130（另有 master 1.1.67 现行版对照）
- Hermes 上游：https://github.com/NousResearch/hermes-agent
- 适配基线：f925b01791fe052e7d55dc975750c0bd985aff91

**0.2.0 具体借用的部分（逐项对应上游文件）：**

| 本仓库实现 | 上游对应 | 借用内容 |
| --- | --- | --- |
| `hermes_purge/armor.py` | `lib/table-key.js`、`lib/table-read.js`、`lib/asset-table.js` | 加密提示词槽位方案：随机 mask 派生密钥、压缩后加密、源码只留密文表 |
| `hermes_purge/armor_runtime.py` | `lib/identity.js` | 把身份/执行稿置顶注入、按预设改写宿主提示词文本、子会话继承提示词的思路 |
| `hermes_purge/refusal.py` | `lib/refusal-recover.js` | 拒答检测正则族（道歉 + 拒绝动词的近邻窗口判定、硬停例外）与续跑文案 |
| `hermes_purge/scrub.py` | `lib/identity.js` 的 replace 表 | "把宿主信任边界/拒绝终局文案改成可用参考"的做法（文案锚点取自 Hermes 源码） |
| `hermes_purge/core.py` 的 `armor` 预设 | `cordis.patch.yml` + 清洗页 | 用预设一次性切换提示词与宿主策略 |
| 侧栏/面板的补丁与提示词页 | `client.js` 清洗页 | 分组展示、按需应用的交互思路 |

原仓库的名称、代码、提示词与素材权利仍归其作者。本声明用于保留来源与署名，不表示任何官方隶属或背书。上游 README 的署名要求（借用名称、思路、代码或提示词必须署名并标明来源仓库）在本文件与 [README](README.md) 中均已满足。
