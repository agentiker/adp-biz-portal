/**
 * Agent 全局 Store Composable
 *
 * 模块作用域单例 ref：所有调用 useAgentStore() 的组件共享同一份响应式数据。
 *
 * 只保留 ADP agent chat 调试页需要的部分：
 *  - 按 applicationId 登记应用模式（Pattern → ChatMode），决定是否走 ClawAgent 流程
 *  - ClawAgent 应用在建会话前需要 agentId：先查本地 /agent/config，未命中才 CopyAgentFromApp 并回写
 *
 * Skills / Plugins / Tools / AgentDetail 相关缓存与 ModifyAgent 系列已随 ADP 管理面能力一并移除。
 */
import { ref, readonly, watch, type Ref, type WatchSource } from 'vue';
import {
    copyAgentFromApp,
    getAgentConfig,
    saveAgentConfig,
    type CopyAgentFromAppPayload,
} from '../service/api';
import type { ChatMode } from '../model/type';

/**
 * 将后端返回的原始 Pattern 值归一化为业务侧统一使用的 ChatMode。
 *  - 'ClawAgent' → 'claw'
 *  - 其它（包括 '' / null / 'agent' / 未来新增值）→ 'standard'
 * 保持与 Index.vue 内的 chatMode computed 完全一致的收敛规则。
 */
const patternToMode = (pattern: string | null | undefined): ChatMode => {
    return pattern === 'ClawAgent' ? 'claw' : 'standard';
};

// ------------------------------ 模块作用域单例 state ------------------------------
/** 按 applicationId 绑定的 agent_id 映射：{ [applicationId]: agentId }（存储 CopyAgentFromApp 返回的 ParentAgentId） */
const agentIdMap = ref<Record<string, string>>({});
/** 按 applicationId 维度的加载状态：{ [applicationId]: boolean } */
const loadingMap = ref<Record<string, boolean>>({});
/** 按 applicationId 维度的 inflight Promise，避免并发重复请求 */
const inflightMap = new Map<string, Promise<string>>();

/**
 * 按 applicationId 缓存的应用 Pattern（来自 ApplicationList 接口）。
 *
 * 仅 Pattern === 'ClawAgent' 的应用才需要走 CopyAgentFromApp / DescribeAgentDetail
 * 一系列 Agent 拓展流程；其它应用（agent / standard 等）都不应触发这些请求，
 * 以避免无谓的接口调用与后端错误。
 *
 * 存储的是归一化后的 ChatMode（'claw' / 'standard'），语义与 Index.vue 的 chatMode computed 一致；
 * 原始 Pattern 字符串在写入时通过 patternToMode() 归一化，避免下游再自己 if === 'ClawAgent'。
 *
 * 判定策略：
 *  - 已注册（曾经 setApplicationModes / setApplicationMode 写入过）且 !== 'claw' → 视为"非 Claw"，跳过
 *  - 未注册（尚未拉到列表 / 外部直接透传） → 保守放行，避免注册滞后导致漏调用
 */
const applicationModeMap = ref<Record<string, ChatMode>>({});


/** fetchAndSetAgentId 选项 */
export interface FetchAgentIdOptions {
    /** 应用 ID（作为存储 key，也透传给 /adp 代理） */
    applicationId: string;

    /**
     * 是否强制刷新（默认 false）。
     * - false：优先复用内存缓存 / 本地后端 DB 中已绑定的 agentId，避免重复 CopyAgentFromApp。
     * - true：跳过内存缓存与本地 DB 查询，强制重新调用 CopyAgentFromApp 生成新的 agentId，
     *         并将结果覆盖写回内存缓存与本地后端 DB（供下次 / 多端复用）。
     *         注：并发的 force 请求仍会通过 inflight 去重，避免用户连点导致重复 copy。
     */
    force?: boolean;
}


/**
 * useAgentStore：返回全局共享的 Agent 上下文状态以及对应的操作方法。
 */
export function useAgentStore() {
    /**
     * 批量登记应用列表的 Pattern。通常在 ApplicationList 接口返回后调用一次即可。
     * 允许多次调用（增量合并）。
     */
    const setApplicationModes = (
        list: Array<{ ApplicationId?: string; Pattern?: string | null }>,
    ) => {
        if (!Array.isArray(list) || list.length === 0) return;
        const next = { ...applicationModeMap.value };
        for (const item of list) {
            const appId = item?.ApplicationId;
            if (!appId) continue;
            // Pattern 允许为 null / '' / 未知值，统一归一化为 ChatMode 后登记
            // （非 'ClawAgent' → 'standard'，视为"已知且非 Claw"）
            next[appId] = patternToMode(item?.Pattern);
        }
        applicationModeMap.value = next;
    };

    /**
     * 单条设置 / 覆盖某个应用的模式。
     * 入参兼容原始 Pattern 字符串（'ClawAgent' / 'agent' / null / ...）与已归一化的 ChatMode（'claw' / 'standard'），
     * 内部统一走 patternToMode 收敛，因此传任意一种都是安全的。
     */
    const setApplicationMode = (
        applicationId: string,
        patternOrMode: string | ChatMode | null | undefined,
    ) => {
        if (!applicationId) return;
        // 'claw' 直接命中；'ClawAgent' 也命中；其它一律 'standard'
        const mode: ChatMode = patternOrMode === 'claw' ? 'claw' : patternToMode(patternOrMode);
        applicationModeMap.value = {
            ...applicationModeMap.value,
            [applicationId]: mode,
        };
    };

    /**
     * 查询指定 applicationId 的 ChatMode。
     *
     * 用于业务层想直接拿到某个应用的模式、又不方便从 Index.vue 透传 prop 的场景
     * （例如某些非 Layout 直连子组件、独立弹窗、hooks 内部判断等）。
     *
     * - 已登记：返回登记时归一化后的 ChatMode
     * - 未登记：返回 'standard'（区别于 isClawAgent 的"保守放行"语义 —— getter 层面
     *   面向业务查询，应给出确定值；网络请求门槛才需要保守放行）
     */
    const getModeByAppId = (applicationId: string): ChatMode => {
        if (!applicationId) return 'standard';
        return applicationModeMap.value[applicationId] ?? 'standard';
    };


    /**
     * 判定指定应用是否需要走 Agent 扩展流程（CopyAgentFromApp / DescribeAgentDetail）。
     *
     * - 已登记：仅 mode === 'claw' 放行
     * - 未登记：保守放行（避免注册滞后导致业务漏请求）
     *
     * 注意此处的"未登记保守放行"与 getModeByAppId 的"未登记返回 standard"故意不一致：
     * 本方法是网络请求门槛，宁可多请求也不能漏；getter 面向业务查询，需要确定值。
     */
    const isClawAgent = (applicationId: string): boolean => {
        if (!applicationId) return false;
        if (!(applicationId in applicationModeMap.value)) return true;
        return applicationModeMap.value[applicationId] === 'claw';
    };

    /**
     * 调用 CopyAgentFromApp 创建用户 Agent，把返回的 ParentAgentId 绑定写入该 applicationId 的槽位。
     * @returns 创建后得到的 ParentAgentId（失败或为空时返回 ''）
     */
    const fetchAndSetAgentId = async (
        options: FetchAgentIdOptions
    ): Promise<string> => {
        const {
            applicationId,
            force = false,
        } = options;

        if (!applicationId) {
            console.warn('[useAgentStore] applicationId 为空，跳过 CopyAgentFromApp');
            return '';
        }

        // 非 ClawAgent 应用不走 CopyAgentFromApp 流程
        if (!isClawAgent(applicationId)) {
            return '';
        }

        // 命中前端内存缓存：仅在非强制刷新时复用。force=true 时跳过，走重新 CopyAgentFromApp。
        if (!force && agentIdMap.value[applicationId]) {
            return agentIdMap.value[applicationId];
        }

        // 已有 inflight 请求则复用，避免并发重复调用（含 force 之间的去重，防止用户连点重复 copy）。
        const inflight = inflightMap.get(applicationId);
        if (inflight) {
            return inflight;
        }

        const task = (async (): Promise<string> => {
            try {
                loadingMap.value = { ...loadingMap.value, [applicationId]: true };

                // 1) 非强制刷新时优先查本地后端 DB，命中则直接返回，不再走外部 ADP 接口。
                //    force=true 时跳过此步，强制走下面的 CopyAgentFromApp 重新生成。
                if (!force) {
                    try {
                        const localResp = await getAgentConfig(
                            applicationId,
                        );
                        const localAgentId = localResp?.AgentId || '';
                        if (localAgentId) {
                            agentIdMap.value = {
                                ...agentIdMap.value,
                                [applicationId]: localAgentId,
                            };
                            return localAgentId;
                        }
                    } catch (e) {
                        // 本地查询失败不阻断主流程，继续走外部接口兜底
                        console.warn(
                            '[useAgentStore] 本地 AgentConfig 查询失败，回退外部接口:',
                            e
                        );
                    }
                }

                // 2) 调用 CopyAgentFromApp 创建用户 Agent
                const payload: CopyAgentFromAppPayload = {
                    AppId: applicationId,
                };
                const resp = await copyAgentFromApp(
                    payload,
                    applicationId,
                );
                const newAgentId = resp?.ParentAgentId || '';

                // 3) 把"新生成的 ParentAgentId"写入 store（最终对外暴露的 id）
                agentIdMap.value = {
                    ...agentIdMap.value,
                    [applicationId]: newAgentId,
                };

                // 4) 回写本地 DB，供下次/多端复用（force 时即覆盖旧绑定；失败不阻断主流程）
                if (newAgentId) {
                    try {
                        await saveAgentConfig(
                            applicationId,
                            newAgentId,
                        );
                    } catch (e) {
                        console.warn(
                            '[useAgentStore] 保存本地 AgentConfig 失败（不影响本次使用）:',
                            e
                        );
                    }
                }

                return newAgentId;
            } catch (error) {
                console.error('[useAgentStore] CopyAgentFromApp 失败:', error);
                return '';
            } finally {
                loadingMap.value = { ...loadingMap.value, [applicationId]: false };
                inflightMap.delete(applicationId);
            }
        })();

        inflightMap.set(applicationId, task);
        return task;
    };

    /**
     * 根据 applicationId 获取已绑定的 agent_id。
     * 如果缓存中已有值则直接返回，否则等待 fetchAndSetAgentId 请求完成后返回。
     */
    const getAgentIdByAppId = async (applicationId: string): Promise<string> => {
        if (!applicationId) return '';
        // 缓存命中直接返回
        if (agentIdMap.value[applicationId]) {
            return agentIdMap.value[applicationId];
        }
        // 非 ClawAgent 不触发外部请求
        if (!isClawAgent(applicationId)) return '';
        // 缓存未命中，触发请求并等待结果
        return fetchAndSetAgentId({ applicationId });
    };

    

    /**
     * 根据 applicationId 获取响应式的 agent_id ComputedRef，
     * 监听一个响应式的 applicationId 源，当其变化时自动调用 fetchAndSetAgentId。
     * 支持传入 Ref<string>、getter 函数 () => string 等。
     * 内部使用 immediate: true，初始值非空时也会立即触发。
     *
     * @param source 响应式 applicationId 来源（Ref<string> 或 getter）
     * @returns 停止监听的函数（stop handle）
     */
    const watchApplicationId = (source: WatchSource<string | undefined>) => {
        return watch(
            source,
            (newVal) => {
                if (!newVal) return;
                // 非 ClawAgent 应用不触发 CopyAgentFromApp
                if (!isClawAgent(newVal)) return;
                fetchAndSetAgentId({ applicationId: newVal });
            },
            { immediate: true },
        );
    };


    return {
        /** 全量 applicationId -> ChatMode 映射（只读响应式引用） */
        applicationModeMap: readonly(applicationModeMap) as Readonly<Ref<Record<string, ChatMode>>>,
        /** 批量登记应用列表的模式（ApplicationList 返回后调用） */
        setApplicationModes,
        /** 单条登记某个应用的模式 */
        setApplicationMode,
        /** 同步查询某个 applicationId 的 ChatMode；未登记返回 'standard' */
        getModeByAppId,
        /** 是否为需要走 Agent 扩展流程的应用（未登记时保守放行） */
        isClawAgent,
        /** 全量 applicationId -> agentId 映射（只读响应式引用） */
        agentIdMap: readonly(agentIdMap) as Readonly<Ref<Record<string, string>>>,
        /** 异步调用 CopyAgentFromApp 并按 applicationId 绑定 agentId */
        fetchAndSetAgentId,
        /** 按 applicationId 异步获取 agentId */
        getAgentIdByAppId,
        /** 监听响应式 applicationId 变化，自动触发 fetchAndSetAgentId */
        watchApplicationId,
    };
}

export default useAgentStore;
