/**
 * MCP 接入教程对话框：分步引导用户把 Nexuz 接入 AI 编码代理（Claude Code / zcode）
 * 并安装 nexuz-mcp 技能。命令行由 bridge.mcpClientConfig 按当前安装形态生成。
 */
import React, { useEffect, useState } from 'react';
import { Check, Copy, Link2 } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { bridge } from '@/bridge';
import { ThemeColors } from '../types';

const SKILL_GITHUB_URL = 'https://github.com/Slocean/Nexuz/tree/main/.agents/skills/nexuz-mcp';

function StepBadge({ n, colors }: { n: number; colors: ThemeColors }) {
  return (
    <span
      className="shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-semibold"
      style={{ backgroundColor: colors.primary, color: '#fff' }}>
      {n}
    </span>
  );
}

function CopyRow({ text, colors, mono = true }: { text: string; colors: ThemeColors; mono?: boolean }) {
  const [copied, setCopied] = useState(false);
  const doCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* 剪贴板不可用时保持静默，用户可手动选择文本 */
    }
  };
  return (
    <div
      className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5"
      style={{ borderColor: colors.border, backgroundColor: colors.surface }}>
      <code
        className={`flex-1 min-w-0 break-all text-[11px] leading-relaxed ${mono ? 'font-mono' : ''}`}
        style={{ color: colors.text }}>
        {text}
      </code>
      <Button type="button" size="sm" variant="outline" className="h-6 px-2 shrink-0" onClick={() => void doCopy()}>
        {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
        {copied ? '已复制' : '复制'}
      </Button>
    </div>
  );
}

function Step({
  n,
  title,
  colors,
  children
}: {
  n: number;
  title: string;
  colors: ThemeColors;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <StepBadge n={n} colors={colors} />
        <h3 className="text-xs font-semibold" style={{ color: colors.text }}>
          {title}
        </h3>
      </div>
      <div className="pl-7 space-y-1.5">{children}</div>
    </div>
  );
}

export default function McpTutorialDialog({
  open,
  onOpenChange,
  colors
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  colors: ThemeColors;
}) {
  const [mcpCommand, setMcpCommand] = useState('');
  const [shellPath, setShellPath] = useState('');
  const [shellMissing, setShellMissing] = useState(false);
  const [packaged, setPackaged] = useState(false);
  const [skillInstalling, setSkillInstalling] = useState(false);
  const [skillMsg, setSkillMsg] = useState('');

  const installSkill = async () => {
    setSkillInstalling(true);
    setSkillMsg('');
    try {
      const res = await bridge.mcpInstallSkill?.();
      if (!res?.ok) {
        setSkillMsg(res?.error || '安装失败');
        return;
      }
      const label = { zcode: 'zcode', claude: 'Claude Code' } as Record<string, string>;
      const lines = Object.entries(res.results || {}).map(([k, r]) => {
        const item = r as { ok: boolean; path?: string; error?: string };
        return item.ok ? `${label[k] || k}：已写入 ${item.path}` : `${label[k] || k}：失败（${item.error}）`;
      });
      setSkillMsg(`安装完成 —— ${lines.join('；')}。新开一个 AI 客户端会话即可生效。`);
    } catch (e: any) {
      setSkillMsg(String(e?.message || e || '安装失败'));
    } finally {
      setSkillInstalling(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await bridge.mcpClientConfig?.();
        if (cancelled || !res?.ok) return;
        setMcpCommand(String(res.command || ''));
        setShellPath(String(res.shell_path || ''));
        setShellMissing(!res.shell_exists);
        setPackaged(/NEXUZ_EXE=/.test(String(res.command || '')));
      } catch {
        /* 状态由空值兜底：展示通用说明 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const rawCommand = `python "${shellPath || '<Nexuz 目录>\\nexuz_mcp.py'}"${packaged ? '（另设环境变量 NEXUZ_EXE=<Nexuz.exe 完整路径>）' : ''}`;
  const secondaryText = { color: colors.secondaryText };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogTitle className="flex items-center gap-2 text-sm">
          <Link2 className="w-4 h-4 shrink-0" style={{ color: colors.primary }} />
          接入教程：把 Nexuz 开放给 AI 编码代理
        </DialogTitle>
        <div className="space-y-4 pt-1">
          <Step n={1} title="确认 Nexuz 与 MCP 服务就绪" colors={colors}>
            <p className="text-xs leading-relaxed" style={secondaryText}>
              保持 Nexuz 运行，并在本页勾选「允许本地 MCP 服务」，状态行显示「运行中」。服务仅监听
              127.0.0.1，令牌每次启动随机生成，只有本机 AI 客户端能连接。
            </p>
          </Step>

          <Step n={2} title="把接入命令注册到你的 AI 客户端" colors={colors}>
            <p className="text-xs leading-relaxed" style={secondaryText}>
              Claude Code：在终端执行下面这条命令（已按当前安装形态生成；应用未运行时会自动拉起 Nexuz）：
            </p>
            {shellMissing ? (
              <p className="text-xs" style={{ color: colors.primary }}>
                未找到壳进程文件 {shellPath || 'nexuz_mcp.py'}（打包版请将 nexuz_mcp.py 放在程序同目录）。
              </p>
            ) : (
              <CopyRow text={mcpCommand} colors={colors} />
            )}
            <p className="text-xs leading-relaxed" style={secondaryText}>
              zcode 及其他 MCP 客户端：以 stdio 方式注册名为 nexuz 的服务器，命令为：
            </p>
            <CopyRow text={rawCommand} colors={colors} />
          </Step>

          <Step n={3} title="验证连接" colors={colors}>
            <p className="text-xs leading-relaxed" style={secondaryText}>
              在 AI 客户端对话里输入「用 Nexuz 查看状态」，它应调用 get_status 返回版本与运行信息；再说「列出可用积木」验证
              list_blocks。连接失败时优先确认：应用正在运行、本页服务已开启、没有多开第二个应用实例（后启动的实例会接管端口文件）。
            </p>
          </Step>

          <Step n={4} title="安装 nexuz-mcp 技能（推荐）" colors={colors}>
            <p className="text-xs leading-relaxed" style={secondaryText}>
              技能教会 AI 代理按正确姿势调用：先查积木参数再执行、屏幕坐标必须来自真实截图、被拒不重试等。
              应用已内置技能文件，点击一键安装到本机（覆盖旧副本，随应用更新保持同步）：
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={skillInstalling}
                onClick={() => void installSkill()}>
                {skillInstalling ? '安装中…' : '一键安装技能到本机'}
              </Button>
            </div>
            {skillMsg ? (
              <p className="text-[11px] leading-relaxed break-all" style={secondaryText}>
                {skillMsg}
              </p>
            ) : null}
            <p className="text-xs leading-relaxed" style={secondaryText}>
              手动安装（可选）：从源码仓库{' '}
              <code className="font-mono">.agents/skills/nexuz-mcp/</code> 或 GitHub 获取
              SKILL.md，把整个 nexuz-mcp 文件夹拷到对应目录：
            </p>
            <CopyRow text={SKILL_GITHUB_URL} colors={colors} />
            <CopyRow text="zcode：%USERPROFILE%\.agents\skills\" colors={colors} mono={false} />
            <CopyRow text="Claude Code：%USERPROFILE%\.claude\skills\" colors={colors} mono={false} />
            <p className="text-xs leading-relaxed" style={secondaryText}>
              新开一个会话生效。之后直接说「用 nexuz 把某目录的图片统一缩放」即可。
            </p>
          </Step>

          <div
            className="rounded-lg border px-3 py-2 space-y-1"
            style={{ borderColor: colors.border, backgroundColor: colors.surface }}>
            <p className="text-[11px] leading-relaxed" style={secondaryText}>
              无需任何开关：除 python_script / run_command / 电源操作 / 自定义积木 / 控制流外，全部积木可被外部
              AI 直接执行；这些拒绝项没有开关、也无法绕过（含子流程与定时任务）。
            </p>
            <p className="text-[11px] leading-relaxed" style={secondaryText}>
              所有调用写入审计日志（数据目录 ai/audit，按日分文件）。
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
