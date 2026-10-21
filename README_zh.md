# SegQC Viewer：分割质控阅片器

用于 CT 膀胱分割人工质控的轻量桌面工具：在轴位 DICOM 图像上叠加 NIfTI 掩膜，将审核人的结论和备注保存到 CSV。当前界面为中文。

[English README](README.md)

![合成 CT 与分割叠加示例](docs/synthetic-demo.png)

截图中的数据由 `scripts/create_demo.py` 人工生成，不含患者数据。

作者：**JQ**（[elaemc0209](https://github.com/elaemc0209)）；邮箱：**3360168387@qq.com**。

## 使用范围与限制

本工具面向科研人工质控，不用于临床诊断。叠加显示前会核对影像几何信息，**不提供通用 DICOM/NIfTI 配准或仿射重采样**。

仅适用于已处于同一体素网格的轴位、单帧 CT 与分割掩膜。NIfTI 掩膜须声明毫米单位并提供有效 `sform`（`sform_code > 0`）；仅有 qform 的文件会被拒绝，需要先用合适的外部软件转换。软件将 NIfTI 的 RAS 仿射转换为 DICOM 的 LPS 坐标，逐层核对方向、原点和间距，平面内容差为 0.001 mm，位置容差为 0.1 mm，不匹配时拒绝加载。几何核对通过不能证明分割内容解剖正确。更换数据集后，仍应使用可靠的参考软件独立核对代表性解剖标志。斜位采集、多帧 DICOM 及同一病例内多个候选 CT 序列不属于当前支持范围。压缩 DICOM 可能需要最小依赖中未包含的像素解码器。

公开仓库仅包含代码及合成测试，不包含患者影像、掩膜、真实病例信息、临床截图或历史评分结果。测试通过不代表临床性能验证，也不代表某个真实数据集已完成空间对齐验证。

## 安装

Windows 是桌面可执行程序的主要目标平台。从源码运行需要 Python 3.12 或更新版本，且 Python 环境须具备 Tk/Tcl 支持。在仓库根目录使用 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

依赖包括 NumPy、pydicom 和 Pillow。可运行 `python -m tkinter` 检查 Tkinter 是否能够打开测试窗口；部分平台需要单独安装系统 Tk 运行库。

## 数据目录

将数据放在仓库之外。病例目录名必须与掩膜文件名严格一致：

```text
data/
  ct/
    case_001/
      slice001.dcm
      slice002.dcm
      ...
    case_002/
      ...
  masks/
    case_001.nii.gz
    case_002.nii.gz
```

每个病例也可使用一个嵌套的 DICOM 序列目录。同一病例存在多个序列时会拒绝加载，应先选择目标序列并整理为单序列，所有切片须具有同一个 `SeriesInstanceUID`。掩膜须为三维、单文件 NIfTI-1 `.nii.gz`，并符合上述几何元数据要求，非零值作为前景显示。软件仅审核 CT 病例目录与掩膜文件名的交集。

## 启动

```powershell
.\.venv\Scripts\python.exe src/segqc_viewer.py --ct-root "D:\data\ct" --mask-dir "D:\data\masks" --output-dir "D:\reviews\session01"
```

打包版接受相同参数：

```powershell
.\segqc-viewer.exe --ct-root "D:\data\ct" --mask-dir "D:\data\masks" --output-dir "D:\reviews\session01"
```

未指定 `--ct-root` 时，会提示选择 CT 根目录。未指定 `--mask-dir` 时，使用可执行程序旁的 `masks`；源码模式则使用 `src/segqc_viewer.py` 旁的 `masks`。输出目录默认同样位于程序目录。建议显式指定具有写入权限的输出目录，并按数据集、审核人分别建立目录，避免同名病例的结果混用。

## 操作与结果

| 操作 | 功能 |
|---|---|
| 滚轮／上、下方向键 | 前后翻层 |
| Page Up／Page Down | 前后跳十层 |
| 左、右方向键 | 上一例／下一例 |
| `1` | 通过（`pass`） |
| `2` | 轻微问题（`minor`） |
| `3` | 失败需重做（`fail`） |
| `4` | 该例排除（`exclude`） |
| `M` | 循环切换填充、轮廓及隐藏掩膜 |
| 鼠标右键拖动 | 调整窗宽、窗位 |

侧栏显示各病例的结论及备注。按提示输入审核人姓名，在备注栏填写问题。评分保存至输出目录的 `质控结果.csv`，字段为 `patient_id`、`grade`、`note`、`scorer`、`time`。进度及显示设置写入 `设置.json`。再次使用同一输出目录时会恢复既有结果及进度。交付前请核对 CSV 已保存且包含所评记录。病例标识、备注及本地路径可能敏感，应按所属单位的数据管理要求保管。

## 测试与 Windows 打包

本次已审核的 Windows 构建使用官方 CPython **3.12.10**。许可核验会拒绝其他原生运行库版本；更换版本前须更新并审核原生组件许可清单。

```powershell
python -m unittest discover -s tests -v
python -m pip install -r requirements-build.txt
python scripts/build_release.py
```

打包脚本使用 PyInstaller 准备 Windows 发布包，构建依赖和输出路径以脚本为准。应在目标操作系统上构建并检查发布包及可执行程序。每次发布可按[发布检查模板](docs/RELEASE_CHECKLIST.md)记录验证结果。

## 许可与作者

项目原创代码采用 [MIT 许可](LICENSE)。第三方组件保留各自许可，重新分发源码或二进制版本时，须查阅[第三方声明](THIRD_PARTY_NOTICES.md)及随包附带的 `licenses/` 目录。项目的 MIT 许可不能替代 Python、Tcl/Tk、NumPy、pydicom、Pillow、PyInstaller 等依赖的许可。

作者及联系方式见仓库许可与项目元数据。问题反馈可通过 GitHub Issues 提交复现步骤、环境信息和合成示例；请勿上传患者数据或可识别身份的截图。
