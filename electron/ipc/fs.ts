import { handleTrusted } from '../trusted-ipc'
import { dialog } from 'electron'
import { readdir, readFile, writeFile, stat, mkdir, rename, rm, open, lstat } from 'fs/promises'
import { join, dirname, parse, resolve } from 'path'
import { existsSync } from 'fs'
import { randomUUID } from 'crypto'
import { homedir } from 'os'

export interface FileEntry {
  name: string
  path: string
  isDirectory: boolean
  size: number
  modified: number
}

const normalizedPath = (value: string) => resolve(value).replace(/[\\/]+$/, '').toLowerCase()

const isProtectedDeleteTarget = (targetPath: string) => {
  const resolved = resolve(targetPath)
  const key = normalizedPath(resolved)
  const protectedPaths = new Set([
    normalizedPath(parse(resolved).root),
    normalizedPath(homedir()),
    normalizedPath(process.cwd()),
  ])
  return protectedPaths.has(key)
}

const atomicWriteUtf8 = async (filePath: string, content: string) => {
  const resolved = resolve(filePath)
  const targetDir = dirname(resolved)
  if (!existsSync(targetDir)) await mkdir(targetDir, { recursive: true })
  const temporary = join(targetDir, `.${parse(resolved).base}.${randomUUID()}.tmp`)
  const handle = await open(temporary, 'wx')
  try {
    await handle.writeFile(content, 'utf-8')
    await handle.sync()
  } finally {
    await handle.close()
  }
  try {
    let lastError: unknown
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        await rename(temporary, resolved)
        return
      } catch (error) {
        lastError = error
        if (attempt < 4) await new Promise(resolveDelay => setTimeout(resolveDelay, 25 * (attempt + 1)))
      }
    }
    throw lastError
  } finally {
    if (existsSync(temporary)) await rm(temporary, { force: true })
  }
}

export function registerFsHandlers() {
  handleTrusted('fs:readDir', async (_event, dirPath: string): Promise<FileEntry[]> => {
    try {
      const entries = await readdir(dirPath, { withFileTypes: true })
      const results: FileEntry[] = []

      for (const entry of entries) {
        if (entry.name.startsWith('.') && entry.name !== '.env.example') continue
        if (['node_modules', '__pycache__', 'dist', 'dist-electron', '.merak'].includes(entry.name)) continue

        const fullPath = join(dirPath, entry.name)
        try {
          const fileStat = await stat(fullPath)
          results.push({
            name: entry.name,
            path: fullPath,
            isDirectory: entry.isDirectory(),
            size: fileStat.size,
            modified: fileStat.mtimeMs,
          })
        } catch { /* skip */ }
      }

      return results.sort((a, b) => {
        if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    } catch {
      return []
    }
  })

  handleTrusted('fs:readFile', async (_event, filePath: string): Promise<string> => {
    return readFile(filePath, 'utf-8')
  })

  handleTrusted('fs:writeFile', async (_event, filePath: string, content: string): Promise<void> => {
    await atomicWriteUtf8(filePath, content)
  })

  handleTrusted('fs:stat', async (_event, filePath: string) => {
    const s = await stat(filePath)
    return { size: s.size, isDirectory: s.isDirectory(), isFile: s.isFile(), modified: s.mtimeMs, created: s.birthtimeMs }
  })

  // 新建文件
  handleTrusted('fs:createFile', async (_event, filePath: string): Promise<boolean> => {
    try {
      const dir = dirname(filePath)
      if (!existsSync(dir)) await mkdir(dir, { recursive: true })
      if (existsSync(filePath)) return false
      await writeFile(filePath, '', { encoding: 'utf-8', flag: 'wx' })
      return true
    } catch { return false }
  })

  // 新建文件夹
  handleTrusted('fs:createDir', async (_event, dirPath: string): Promise<boolean> => {
    try {
      await mkdir(dirPath, { recursive: true })
      return true
    } catch { return false }
  })

  // 重命名
  handleTrusted('fs:rename', async (_event, oldPath: string, newPath: string): Promise<boolean> => {
    try {
      if (existsSync(newPath)) return false
      await rename(oldPath, newPath)
      return true
    } catch { return false }
  })

  // 删除（文件或文件夹）
  handleTrusted('fs:delete', async (_event, targetPath: string): Promise<boolean> => {
    try {
      if (isProtectedDeleteTarget(targetPath)) return false
      const targetStat = await lstat(targetPath)
      if (targetStat.isDirectory() && !targetStat.isSymbolicLink()) {
        if (existsSync(join(targetPath, '.git')) || existsSync(join(targetPath, '.merak'))) return false
        await rm(targetPath, { recursive: true, force: false })
      } else {
        await rm(targetPath, { force: false })
      }
      return true
    } catch { return false }
  })

  // 移动（拖拽）
  handleTrusted('fs:move', async (_event, srcPath: string, destDir: string): Promise<boolean> => {
    try {
      const name = srcPath.split(/[\\/]/).pop()!
      const destPath = join(destDir, name)
      if (normalizedPath(srcPath) === normalizedPath(destPath) || existsSync(destPath)) return false
      await rename(srcPath, destPath)
      return true
    } catch { return false }
  })

  // 打开文件夹选择器
  handleTrusted('fs:openFolder', async () => {
    const result = await dialog.showOpenDialog({ properties: ['openDirectory'], title: 'Open Research Project' })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  // 新建项目（选位置 + 创建文件夹 + 初始化 .merak）
  handleTrusted('fs:newProject', async (_event, name: string) => {
    const result = await dialog.showOpenDialog({ properties: ['openDirectory'], title: 'Choose location for new project' })
    if (result.canceled || result.filePaths.length === 0) return null
    const projectDir = join(result.filePaths[0], name)
    await mkdir(projectDir, { recursive: true })
    await mkdir(join(projectDir, '.merak'), { recursive: true })
    await atomicWriteUtf8(join(projectDir, '.merak', 'memory.json'), '{"research_direction":"","entries":[],"workflow_history":[]}')
    await atomicWriteUtf8(join(projectDir, 'README.md'), `# ${name}\n\nMERAK research project.\n`)
    return projectDir
  })

  // 打开文件选择器
  handleTrusted('fs:openFile', async (_event, filters?: Array<{ name: string; extensions: string[] }>) => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      title: 'Select File',
      filters: filters || [{ name: 'All Files', extensions: ['*'] }, { name: 'PDF/LaTeX', extensions: ['pdf', 'tex'] }],
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })
}
