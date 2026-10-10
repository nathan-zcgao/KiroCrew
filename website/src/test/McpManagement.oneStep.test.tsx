// MCP Management: one tap shares a server.
//
// Contract under test:
// - turning a row's switch on is ONE request: no review, no approve button, no
//   expected_launch (the endpoint records the exact launch itself)
// - a row turned on while sharing is off turns sharing on as well
// - a server that can never be shared shows a disabled switch and one line why
// - a shared row whose launch is not recorded yet reads "Tap to share", switch
//   off, and one tap records it
// - the saving shown is the MEASURED number the gateway sent, and no number at
//   all when it sent none
// - what a server runs is only under a collapsed Details, never in the main flow
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api/client'
import { McpManagement } from '../pages/settings/McpManagement'

function server(over: Record<string, unknown> = {}) {
  return {
    name: 'alpha-mcp',
    stub: false,
    can_stub: true,
    in_allowlist: false,
    entry_poolable: false,
    agents: ['kirocrew'],
    transport: 'stdio',
    denylisted: false,
    share_blocked: null,
    saves_bytes: null,
    ...over,
  }
}

const status = (over: Record<string, unknown> = {}) => ({
  enabled: false,
  stub: [] as string[],
  stub_count: 0,
  running: false,
  ping_ok: false,
  supported: true,
  ...over,
})

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <McpManagement />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(cleanup)

describe('one-step sharing', () => {
  it('shares on one tap, with no review and no expected launch', async () => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(status({ enabled: true }) as never)
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({ servers: [server()] } as never)
    const preview = vi.spyOn(api, 'mcpGatewayLaunchPreview')
    const setStub = vi.spyOn(api, 'mcpGatewaySetStub').mockResolvedValue({
      ok: true, name: 'alpha-mcp', stub: true, restart_required: true,
    } as never)

    mount()
    fireEvent.click(await screen.findByRole('switch', { name: 'Share alpha-mcp' }))

    await waitFor(() => expect(setStub).toHaveBeenCalledTimes(1))
    expect(setStub).toHaveBeenCalledWith('alpha-mcp', true)
    // Nothing was read to show first, and nothing asks a second time.
    expect(preview).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('turns sharing on too when it was off', async () => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(status({ enabled: false }) as never)
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({ servers: [server()] } as never)
    vi.spyOn(api, 'mcpGatewaySetStub').mockResolvedValue({ ok: true, name: 'alpha-mcp', stub: true } as never)
    const enable = vi.spyOn(api, 'mcpGatewayEnable').mockResolvedValue({ ping_ok: true } as never)

    mount()
    fireEvent.click(await screen.findByRole('switch', { name: 'Share alpha-mcp' }))

    await waitFor(() => expect(enable).toHaveBeenCalledWith(true))
  })

  it('turns sharing off in one tap', async () => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(status({ enabled: true, stub: ['alpha-mcp'] }) as never)
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({
      servers: [server({ stub: true, in_allowlist: true })],
    } as never)
    const setStub = vi.spyOn(api, 'mcpGatewaySetStub').mockResolvedValue({ ok: true, name: 'alpha-mcp', stub: false } as never)

    mount()
    fireEvent.click(await screen.findByRole('switch', { name: 'Share alpha-mcp' }))

    await waitFor(() => expect(setStub).toHaveBeenCalledWith('alpha-mcp', false))
  })

  it.each([
    ['credential_vending', 'gives each chat its own credentials'],
    ['needs_tenant_nonce', 'each chat needs its own copy'],
    ['computer_use', 'it controls this computer'],
  ])('refuses %s with a disabled switch and one line why', async (code, reason) => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(status({ enabled: true }) as never)
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({
      servers: [server({ name: 'creds-agent', share_blocked: code })],
    } as never)
    const setStub = vi.spyOn(api, 'mcpGatewaySetStub')

    mount()
    const sw = await screen.findByRole('switch', { name: 'Share creds-agent' })
    expect((sw as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(new RegExp(`Can't share: ${reason}`))).toBeTruthy()
    fireEvent.click(sw)
    expect(setStub).not.toHaveBeenCalled()
  })

  it('needs one tap to share a row whose launch is not recorded yet', async () => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(
      status({
        enabled: true,
        stub: ['alpha-mcp'],
        launch_refused: { 'alpha-mcp': { reason: 'changed_needs_reapproval' } },
      }) as never,
    )
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({
      servers: [server({ stub: true, in_allowlist: true })],
    } as never)
    const setStub = vi.spyOn(api, 'mcpGatewaySetStub').mockResolvedValue({ ok: true, name: 'alpha-mcp', stub: true } as never)

    mount()
    const sw = await screen.findByRole('switch', { name: 'Share alpha-mcp' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    expect(screen.getAllByText('Tap to share').length).toBeGreaterThan(0)
    fireEvent.click(sw)

    await waitFor(() => expect(setStub).toHaveBeenCalledWith('alpha-mcp', true))
    expect(setStub).toHaveBeenCalledTimes(1)
  })
})

describe('the saving shown', () => {
  it('is the measured number the gateway sent', async () => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(status() as never)
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({
      servers: [server({ saves_bytes: 240_000_000 })],
    } as never)

    mount()
    const hint = await screen.findByText(/^Saves \d/)
    // The number is the gateway's measurement, formatted; not a figure of ours.
    expect(hint.textContent).toMatch(/^Saves 240\s?MB$/)
  })

  it('carries no number when there is no measurement', async () => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(status() as never)
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({
      servers: [server({ saves_bytes: null })],
    } as never)

    mount()
    const hint = await screen.findByText('Saves memory')
    expect(hint.textContent).not.toMatch(/\d/)
  })

  it('is not shown for a server already shared', async () => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(status({ enabled: true, stub: ['alpha-mcp'] }) as never)
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({
      servers: [server({ stub: true, in_allowlist: true })],
    } as never)

    mount()
    await screen.findByRole('switch', { name: 'Share alpha-mcp' })
    expect(screen.queryByText(/^Saves/)).toBeNull()
  })
})

describe('details', () => {
  it('reads what a server runs only when opened, and lists env names before values', async () => {
    vi.spyOn(api, 'mcpGatewayStatus').mockResolvedValue(status() as never)
    vi.spyOn(api, 'mcpGatewayServers').mockResolvedValue({ servers: [server()] } as never)
    const preview = vi.spyOn(api, 'mcpGatewayLaunchPreview').mockResolvedValue({
      name: 'alpha-mcp',
      commands: [['/opt/alpha', '--one'], ['/opt/alpha', '--one']],
      envs: [['PATH=/usr/bin', 'TOKEN=${TOKEN}'], ['PATH=/usr/bin:/bin']],
      complete: true,
    } as never)

    const { container } = mount()
    await screen.findByRole('switch', { name: 'Share alpha-mcp' })
    expect(preview).not.toHaveBeenCalled()
    expect(screen.queryByText('/opt/alpha --one')).toBeNull()

    const details = container.querySelector('details') as HTMLDetailsElement
    details.open = true
    fireEvent(details, new Event('toggle'))

    await waitFor(() => expect(preview).toHaveBeenCalledWith('alpha-mcp'))
    expect(await screen.findByText('Variants: 2')).toBeTruthy()
    expect(screen.getAllByText('/opt/alpha --one')).toHaveLength(2)
    expect(screen.getByText('PATH, TOKEN')).toBeTruthy()
    expect(screen.getByText('PATH=/usr/bin:/bin')).toBeTruthy()
  })
})
