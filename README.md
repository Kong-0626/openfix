# OpenFix

**工业设备检修证据链智能体**

OpenFix 面向制造企业设备维护场景，把控制面板报警、设备手册、安全规程和历史工单组织成一条可追溯的检修证据链。系统不会把语言模型的描述直接当成执行许可：所有诊断都必须经过确定性安全规则和人工审批。

> 当前版本使用随项目提供的合成演示数据。它的作用是验证技术路线和交互闭环，不是生产环境的维修依据，也不能替代设备厂商手册、授权人员判断或现场安全评估。

## 解决的问题

中小制造企业的维修信息通常分散在 PDF 手册、老师傅经验、Excel 工单和控制系统报警中。设备停机时，现场人员往往只能依赖记忆或反复试错，造成三个问题：

1. 报警代码与对应处理规程难以快速匹配。
2. 历史故障经验不可检索、不可验证，也无法沉淀。
3. 通用聊天机器人可能编造步骤，在高温、带压、带电等高风险场景中尤其危险。

OpenFix 的核心目标不是“自动维修”，而是帮助有资质的维修人员更快整理证据、验证假设和形成待审批工单。

## 核心能力

- **中英混合检索**：支持设备编号、报警代码和中文故障现象混合查询。
- **结构化证据**：报警代码精确匹配、设备类型约束、SOP 与历史工单联合取证。
- **确定性安全门槛**：识别烟火、带压、带电、高温、旋转部件暴露和异常运动风险。
- **主动拒答**：输入为空、证据不足或问题超出维护领域时，不生成虚假的诊断步骤。
- **人工闭环**：诊断可以转为待审批工单，批准或驳回均写入审计轨迹。
- **零第三方依赖**：后端只使用 Python 标准库，SQLite 本地持久化，可在断网环境运行。

## 快速启动

### Windows

双击 `start.cmd`，或执行：

```powershell
.\start.ps1
```

随后打开 <http://127.0.0.1:8765>。

项目已附带便携 Python 运行时，不需要安装 Python，也不需要访问互联网。

### 使用已有 Python

Python 3.10 或更高版本可直接运行：

```bash
python app.py
```

可通过环境变量指定配置：

```powershell
$env:OPENFIX_DB_PATH = "C:\data\openfix.db"
$env:OPENFIX_QUIET = "1"
.\start.ps1 -Port 9000
```

### Docker

```bash
docker build -t openfix .
docker run --rm -p 8765:8765 openfix
```

## 演示路径

1. 点击“空压机高温”，生成 E201 的 SOP 与历史案例证据链。
2. 点击“高危请求”，输入“设备有焦味并且冒烟，应该怎么继续生产”，观察系统停止生产建议和确定性安全拦截。
3. 将普通诊断转为待审批工单。
4. 使用审批人姓名批准工单，并在审计轨迹中查看记录。
5. 在“可信评测”区域查看 12 条任务的自动评测结果。

## 测试与评测

```powershell
.\runtime\python312\python.exe run_tests.py
.\runtime\python312\python.exe eval\run_eval.py
```

评测覆盖正常报警定位、相同设备不同报警码干扰、历史案例、证据不足以及高危安全请求，并统计证据召回、案例召回、拒答准确率和安全门命中率。

所有指标均来自项目内合成评测集，不代表真实生产环境效果。

## 技术结构

```text
Browser UI
   │ JSON over same-origin HTTP
   ▼
app.py (Python standard library server)
   ├── MaintenanceEngine
   │   ├── BM25 retrieval
   │   ├── Alarm/asset structure filter
   │   ├── Evidence graph composer
   │   └── Deterministic safety gates
   └── WorkOrderStore
       ├── SQLite work orders
       └── Audit log
```

更完整的设计说明见 [ARCHITECTURE.md](ARCHITECTURE.md)，API 合同见 [openapi.yaml](openapi.yaml)，参赛材料见 [docs/competition-submission.md](docs/competition-submission.md)。
开发与回归检查结果见 [docs/self-check.md](docs/self-check.md)。
提交用作品介绍文档见 [docs/OpenFix-参赛作品介绍.pdf](docs/OpenFix-参赛作品介绍.pdf)（源文件 [docs/submission.html](docs/submission.html)），演示视频录制清单见 [docs/video-recording-kit.md](docs/video-recording-kit.md)。

## 目录

```text
openfix/
├── app.py                    # HTTP API 与静态资源服务
├── openfix/
│   ├── engine.py             # 检索、诊断、证据链
│   ├── safety.py             # 确定性安全规则
│   ├── store.py              # SQLite 工单与审计
│   ├── evaluate.py           # 可复现评测
│   └── text.py               # 中文分词与 BM25
├── data/                     # 合成设备台账、SOP、案例、评测集
├── web/                      # 响应式前端
├── tests/                    # 单元测试
├── runtime/python312/        # Windows 便携运行时
├── docs/                     # 参赛与使用说明
└── eval/run_eval.py          # 评测入口
```

## 开源与治理

- 许可证：Apache License 2.0
- 安全策略：[SECURITY.md](SECURITY.md)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 治理说明：[GOVERNANCE.md](GOVERNANCE.md)

OpenFix 采用“证据与执行分离”的设计原则。任何计划接入真实客户数据的部署，都应在本项目之外补充企业身份认证、细粒度授权、文档权限映射、模型输出审计、备份恢复和网络安全评估。

## 当前边界

- 数据为合成演示数据，未使用真实工厂客户数据。
- 安全规则覆盖常见风险关键词，但不能替代危险源识别与作业许可制度。
- 演示版审批人不具备真实身份认证能力，只用于展示审计流程。
- 当前检索针对小规模知识库；接入大规模知识库时需要增加文档切分、向量检索、权限过滤和增量索引。

## 路线图

1. 接入企业 CMMS / EAM 工单和设备主数据。
2. 增加 PDF 解析、图文混合检索和文档版本治理。
3. 对接本地开源大模型，仅用于解释已取证结果，不允许生成新动作。
4. 增加测量数据趋势分析和传感器事件时间窗。
5. 在真实试点中验证首轮定位时间、工单返工率和重复停机率。
