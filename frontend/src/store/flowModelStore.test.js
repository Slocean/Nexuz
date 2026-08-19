import { beforeEach, describe, expect, it } from 'vitest';
import { useFlowStore } from './flowModelStore';

describe('flow store contract', () => {
  beforeEach(() => {
    useFlowStore.getState().setFlow(
      { name: 'empty', entry: null, nodes: {}, variables: {}, breakpoints: [] },
      null,
    );
  });

  it('replaces a flow atomically and normalizes breakpoint IDs', () => {
    useFlowStore.getState().setFlow(
      {
        name: 'demo',
        entry: '1',
        nodes: { 1: { type: 'delay', params: { ms: 10 } } },
        variables: { count: 2 },
        breakpoints: [1],
      },
      'demo.flow.json',
    );

    const state = useFlowStore.getState();
    expect(state.filePath).toBe('demo.flow.json');
    expect(state.flow.entry).toBe('1');
    expect(state.flow.breakpoints).toEqual(['1']);
    expect(state.past).toEqual([]);
    expect(state.future).toEqual([]);
  });

  it('preserves legacy policy absence and explicit safe policy', () => {
    useFlowStore.getState().setFlow({ entry: null, nodes: {} });
    expect(useFlowStore.getState().flow).not.toHaveProperty('execution_policy');

    useFlowStore.getState().setFlow({
      entry: null,
      nodes: {},
      execution_policy: { mode: 'safe' },
    });
    expect(useFlowStore.getState().flow.execution_policy).toEqual({ mode: 'safe' });
  });

  it('duplicates linked nodes with remapped edges and offset positions', () => {
    useFlowStore.getState().setFlow({
      entry: 'a',
      nodes: {
        a: { type: 'delay', params: {}, next: 'b', position: { x: 10, y: 20 } },
        b: { type: 'delay', params: {}, next: null, position: { x: 30, y: 40 } },
      },
    });

    const [copyA, copyB] = useFlowStore.getState().duplicateNodes(
      ['a', 'b'],
      { x: 5, y: 7 },
    );
    const nodes = useFlowStore.getState().flow.nodes;

    expect(nodes[copyA].next).toBe(copyB);
    expect(nodes[copyA].position).toEqual({ x: 15, y: 27 });
    expect(nodes[copyB].position).toEqual({ x: 35, y: 47 });
    expect(useFlowStore.getState().selectedNodeId).toBe(copyB);
  });
});
