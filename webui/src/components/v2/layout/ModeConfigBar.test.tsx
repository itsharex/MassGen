import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ModeConfigBar } from './ModeConfigBar';
import { useModeStore } from '../../../stores/v2/modeStore';

describe('ModeConfigBar', () => {
  beforeEach(() => {
    useModeStore.getState().reset();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders mode toggles', () => {
    render(<ModeConfigBar />);
    expect(screen.getByText('Parallel')).toBeDefined();
    expect(screen.getByText('Decomp')).toBeDefined();
    expect(screen.getByText('Multi')).toBeDefined();
    expect(screen.getByText('Single')).toBeDefined();
    expect(screen.getByText('Refine')).toBeDefined();
    expect(screen.getByText('Quick')).toBeDefined();
  });

  it('renders agent config controls', () => {
    render(<ModeConfigBar />);
    expect(screen.getByTestId('agent-count-stepper')).toBeDefined();
    expect(screen.getByTestId('agent-summary-btn')).toBeDefined();
    expect(screen.getByText('Docker')).toBeDefined();
  });

  it('renders plan mode dropdown', () => {
    render(<ModeConfigBar />);
    expect(screen.getByTestId('dropdown-plan-mode')).toBeDefined();
    expect(screen.getByText('Normal')).toBeDefined();
  });

  it('renders personas dropdown', () => {
    render(<ModeConfigBar />);
    expect(screen.getByTestId('dropdown-personas')).toBeDefined();
    expect(screen.getByText('No Personas')).toBeDefined();
  });

  it('clicking coordination toggle updates store', () => {
    render(<ModeConfigBar />);
    expect(useModeStore.getState().coordinationMode).toBe('parallel');

    // Inactive option is a button — click to switch
    fireEvent.click(screen.getByText('Decomp'));
    expect(useModeStore.getState().coordinationMode).toBe('decomposition');

    // After switch, "Parallel" is now the inactive button
    fireEvent.click(screen.getByText('Parallel'));
    expect(useModeStore.getState().coordinationMode).toBe('parallel');
  });

  it('clicking agent mode toggle updates store', () => {
    render(<ModeConfigBar />);
    fireEvent.click(screen.getByText('Single'));
    expect(useModeStore.getState().agentMode).toBe('single');

    fireEvent.click(screen.getByText('Multi'));
    expect(useModeStore.getState().agentMode).toBe('multi');
  });

  it('clicking refinement toggle updates store', () => {
    render(<ModeConfigBar />);
    fireEvent.click(screen.getByText('Quick'));
    expect(useModeStore.getState().refinementEnabled).toBe(false);

    fireEvent.click(screen.getByText('Refine'));
    expect(useModeStore.getState().refinementEnabled).toBe(true);
  });

  it('execution lock dims controls', () => {
    useModeStore.getState().lock();
    render(<ModeConfigBar />);
    const bar = screen.getByTestId('mode-config-bar');
    expect(bar.className).toContain('opacity-50');
    expect(bar.className).toContain('pointer-events-none');
  });

  it('docker toggle changes store', () => {
    render(<ModeConfigBar />);
    const dockerBtn = screen.getByTestId('docker-toggle');
    fireEvent.click(dockerBtn);
    expect(useModeStore.getState().dockerEnabled).toBe(true);
  });

  describe('plan mode dropdown', () => {
    it('opens and selects plan mode', () => {
      render(<ModeConfigBar />);
      const dropdown = screen.getByTestId('dropdown-plan-mode');

      // Open dropdown
      fireEvent.click(dropdown.querySelector('button')!);
      expect(screen.getByTestId('dropdown-plan-mode-menu')).toBeDefined();

      // Select Plan
      fireEvent.click(screen.getByText('Plan'));
      expect(useModeStore.getState().planMode).toBe('plan');
    });
  });

  describe('personas dropdown', () => {
    it('opens and selects persona mode', () => {
      render(<ModeConfigBar />);
      const dropdown = screen.getByTestId('dropdown-personas');

      // Open dropdown
      fireEvent.click(dropdown.querySelector('button')!);
      expect(screen.getByTestId('dropdown-personas-menu')).toBeDefined();

      // Select Perspective
      fireEvent.click(screen.getByText('Perspective'));
      expect(useModeStore.getState().personasMode).toBe('perspective');
    });
  });

  describe('max rounds selector', () => {
    it('shows when refinement is enabled', () => {
      render(<ModeConfigBar />);
      expect(screen.getByTestId('max-rounds-selector')).toBeDefined();
    });

    it('hidden when refinement is disabled (Quick mode)', () => {
      useModeStore.getState().setRefinementEnabled(false);
      render(<ModeConfigBar />);
      expect(screen.queryByTestId('max-rounds-selector')).toBeNull();
    });

    it('changing select updates store', () => {
      render(<ModeConfigBar />);
      const select = screen.getByTestId('max-rounds-select') as HTMLSelectElement;
      fireEvent.change(select, { target: { value: '3' } });
      expect(useModeStore.getState().maxAnswers).toBe(3);
    });

    it('selecting default value (5) sets maxAnswers to null', () => {
      useModeStore.getState().setMaxAnswers(3);
      render(<ModeConfigBar />);
      const select = screen.getByTestId('max-rounds-select') as HTMLSelectElement;
      fireEvent.change(select, { target: { value: '5' } });
      expect(useModeStore.getState().maxAnswers).toBeNull();
    });
  });

  describe('agent count stepper', () => {
    it('clicking + increments agent count from null to 1', () => {
      render(<ModeConfigBar />);
      expect(useModeStore.getState().agentCount).toBeNull();

      fireEvent.click(screen.getByTestId('agent-count-increment'));
      expect(useModeStore.getState().agentCount).toBe(1);
    });

    it('clicking + increments count', () => {
      useModeStore.getState().setAgentCount(3);
      render(<ModeConfigBar />);

      fireEvent.click(screen.getByTestId('agent-count-increment'));
      expect(useModeStore.getState().agentCount).toBe(4);
    });

    it('clicking - at null stays null', () => {
      render(<ModeConfigBar />);
      expect(useModeStore.getState().agentCount).toBeNull();

      fireEvent.click(screen.getByTestId('agent-count-decrement'));
      expect(useModeStore.getState().agentCount).toBeNull();
    });

    it('clicking - at 1 goes to null', () => {
      useModeStore.getState().setAgentCount(1);
      render(<ModeConfigBar />);

      fireEvent.click(screen.getByTestId('agent-count-decrement'));
      expect(useModeStore.getState().agentCount).toBeNull();
    });

    it('shows "Config" when agentCount is null', () => {
      render(<ModeConfigBar />);
      expect(screen.getByTestId('agent-count-value').textContent).toBe('Config');
    });

    it('shows number when agentCount is set', () => {
      useModeStore.getState().setAgentCount(5);
      render(<ModeConfigBar />);
      expect(screen.getByTestId('agent-count-value').textContent).toBe('5');
    });
  });

  describe('first-time setup', () => {
    it('agent drawer shows save button when needsFirstTimeSetup is true', () => {
      useModeStore.setState({ needsFirstTimeSetup: true });
      useModeStore.getState().setAgentCount(2);
      render(<ModeConfigBar />);

      // Open the drawer by clicking the agent summary area
      const summary = screen.getByTestId('agent-summary-btn');
      fireEvent.click(summary);
      expect(screen.getByTestId('agent-drawer')).toBeDefined();
      expect(screen.getByTestId('save-and-start-btn')).toBeDefined();
      expect(screen.getByText('Save & Start')).toBeDefined();
    });

    it('agent drawer does not show save button when not first time', () => {
      useModeStore.setState({ needsFirstTimeSetup: false });
      useModeStore.getState().setAgentCount(2);
      render(<ModeConfigBar />);

      const summary = screen.getByTestId('agent-summary-btn');
      fireEvent.click(summary);
      expect(screen.getByTestId('agent-drawer')).toBeDefined();
      expect(screen.queryByTestId('save-and-start-btn')).toBeNull();
    });
  });

  describe('agent summary', () => {
    it('shows "from config" when count is null', () => {
      render(<ModeConfigBar />);
      expect(screen.getByText('from config')).toBeDefined();
    });

    it('shows model chips when count is set', () => {
      useModeStore.getState().setAgentCount(2);
      useModeStore.getState().setAgentConfig(0, { provider: 'openai', model: 'gpt-4o' });
      render(<ModeConfigBar />);
      const btn = screen.getByTestId('agent-summary-btn');
      expect(btn.textContent).toContain('openai');
      expect(btn.textContent).toContain('gpt-4o');
    });

    it('clicking agent summary opens drawer', () => {
      useModeStore.getState().setAgentCount(2);
      render(<ModeConfigBar />);

      // Clicking anywhere on the agent summary area opens the drawer
      const summary = screen.getByTestId('agent-summary-btn');
      fireEvent.click(summary);
      expect(screen.getByTestId('agent-drawer')).toBeDefined();
    });

    it('clicking + opens drawer', () => {
      useModeStore.getState().setAgentCount(2);
      render(<ModeConfigBar />);

      fireEvent.click(screen.getByTestId('agent-count-increment'));
      expect(screen.getByTestId('agent-drawer')).toBeDefined();
    });
  });
});
