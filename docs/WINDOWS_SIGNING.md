# Windows 代码签名（Authenticode）

未签名的 `Nexuz.exe`（尤其是 PyInstaller 打包）很容易被 Windows Defender / SmartScreen 拦截或删除。  
**真正有效**的方式是购买并配置 **OV / EV 代码签名证书**；自签名只能缓解「未知发布者」，无法完全免杀。

## 推荐流程（有正式证书）

1. 向 DigiCert / Sectigo / GlobalSign 等购买 **Code Signing**（OV 即可起步，EV 对 SmartScreen 更好）
2. 导出为 `.pfx`，并设导出密码
3. 生成 base64：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("your.pfx")) | Set-Clipboard
```

4. GitHub 仓库 → **Settings → Secrets and variables → Actions** 添加：

| Secret | 值 |
|--------|-----|
| `WINDOWS_CERTIFICATE` | pfx 的 base64（一行） |
| `WINDOWS_CERTIFICATE_PASSWORD` | pfx 导出密码 |

5. 再跑 `release.bat`：Action 会在打包时嵌入证书 SHA-256 信任锚，随后签名、生成
   `Nexuz.exe.sha256` 并上传两个文件。缺少任一 Secret 会直接终止**正式** Release。

## 两条发版通道

| 脚本 | Tag | 签名 | 用途 |
|------|-----|------|------|
| `release.bat` / `python trigger_release.py` | `vX.Y.Z` | **必须** Secrets | 正式包、可走热更新信任锚 |
| `release_unsigned.bat` / `python trigger_release.py --unsigned` | `unsigned-vX.Y.Z` | 跳过 | 内测；Release 标为 pre-release；**不写信任锚，客户端热更新应拒绝** |

未配置证书时请用未签名通道，不要改正式 `v*` 门禁。

## 临时自签名（开发 / 过渡）

```powershell
.\scripts\new_codesign_cert.ps1
```

按脚本提示把生成的 base64 / 密码填进上述两个 Secrets。  
自签名仍可能被 Defender 报毒，但比完全不签好一些；请尽快换成正式证书。  
`signtool verify /pa` 对自签名会失败（无受信任根），Release 脚本在确认已带签名者后会接受这种情况。

## 本地签名

```powershell
python package.py
.\scripts\sign_exe.ps1 -ExePath dist\Nexuz.exe -PfxPath .codesign\nexuz-codesign.pfx -Password "你的密码"
```

## 注意

- `.codesign/`、`*.pfx` 不要提交进 git
- 自动更新会校验固定仓库、SHA-256、Authenticode 和内置证书指纹；普通本地打包未设置
  `NEXUZ_SIGNER_CERT_SHA256` 时会禁用自动更新。
- 证书轮换必须先用旧证书签发一个同时信任新证书的过渡版本，再切换 Release Secret；
  否则旧客户端会按设计拒绝新证书签名的安装包。
- 若仍被删：把 exe 提交 [Microsoft 误报申诉](https://www.microsoft.com/wdsi/filesubmission)，并积累签名后的下载信誉
