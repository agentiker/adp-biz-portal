/**
 * 反问澄清（questionnaire）协议适配层。
 *
 * 职责：把后端下发的原始 questionnaire 结构与渲染层（ClassifyTag / ClassifySummary）
 * 需要的结构互相转换，并构造上行提交所需的 answers。
 *
 * 设计约束：
 *   - 后端协议与 smart-webim / gpt-demo 完全一致，且不可变更，因此本模块的字段
 *     命名与转换规则严格对齐 smart-webim 的实现，不做「优化」。
 *   - 「其他」选项由前端自动追加（后端不下发），提交时以用户输入的文本替代其 label。
 *   - 历史回显通过「问题文本 + 选项文案」反查下标，这是后端协议决定的，
 *     同一题存在重复 label 时会命中首个，与 smart-webim 行为保持一致。
 *   - 本模块为纯函数集合，不依赖 Vue，便于单测。
 */

import type {
  Content,
  NormalizedQuestionnaire,
  NormalizedQuestionnaireOption,
  NormalizedQuestionnaireQuestion,
  Questionnaire,
  QuestionnaireAnswer,
  QuestionnaireDefaultAnswer,
  QuestionnaireOption,
  QuestionnaireSubmitItem,
  QuestionnaireSummaryItem,
} from '../model/chat-v2';
import { QuestionnaireQuestionType } from '../model/chat-v2';

/** 澄清内容在 Content 中的类型标识 */
export const QUESTIONNAIRE_CONTENT_TYPE = 'questionnaire';

/** 「其他」选项补充输入的最大字数，与 smart-webim 保持一致 */
export const OTHER_INPUT_MAX_LENGTH = 1000;

/**
 * 判断指定下标之后是否还存在用户 Record（反问澄清「已过期」判定用）。
 *
 * 用户没有提交/跳过澄清就继续发起了新一轮对话时，澄清卡应折叠为
 * 「已澄清 0 个问题」且不再允许提交。
 *
 * @param list 完整的 Record 列表
 * @param index 当前 Record 在列表中的下标
 */
export function hasSubsequentUserRecord(
    list: Array<{ Role?: string }>,
    index: number
): boolean {
    for (let i = index + 1; i < list.length; i++) {
        if (list[i]?.Role === 'user') return true;
    }
    return false;
}

/**
 * 判断当前 assistant Record 之后的**第一条**用户 Record 是否是主动"跳过"（纯文本跳过文案）。
 *
 * 对齐 webim `ReplyRenderer._isQuestionnaireSkippedInHistory`：
 * 用户点击"跳过"后上行的是纯文本消息，页面刷新/分享落地页仅凭
 * hasSubsequentUserRecord（=true）只能得到「已过期」语义；这里进一步识别
 * "跳过"文本，让 ChatItem 直接把它当作"已提交"处理。
 *
 * 注意：只判断**紧邻的下一条 user record**——若中间已经又开始了别的对话，就不算跳过历史。
 *
 * @param list     完整的 Record 列表
 * @param index    当前 Record 在列表中的下标
 * @param skipText 当前语言下的"跳过"文案（如「跳过」/「Skip」）
 */
export function isHistoryQuestionnaireSkipped(
    list: Array<{ Role?: string; Messages?: Array<{ Type?: string; Contents?: Content[] }> }>,
    index: number,
    skipText: string
): boolean {
    const text = (skipText || '跳过').trim();
    for (let i = index + 1; i < list.length; i++) {
        const next = list[i];
        if (next?.Role !== 'user') continue;
        // 找到之后的第一条 user record，判断其是否为纯文本"跳过"
        const messages = next.Messages ?? [];
        const primary = messages.find(m => m.Type === 'question') ?? messages[0];
        const contents = primary?.Contents ?? [];
        if (!contents.length) return false;
        // 只允许 text 类型且文本为"跳过"；其它 content 类型直接判否
        for (const c of contents) {
            if (c.Type === 'text') {
                if ((c.Text ?? '').trim() === text) return true;
                return false;
            }
            // 非 text（file/widget/questionnaire 等）不视为跳过
            return false;
        }
        return false;
    }
    return false;
}

/**
 * 从消息的 contents 中提取澄清内容体。
 * @param contents 消息的内容数组
 * @returns 澄清内容体；不存在时返回 null
 */
export function pickQuestionnaireContent(
    contents?: Content[]
): Questionnaire | null {
    if (!contents || !contents.length) return null;
    const item = contents.find((c) => c?.Type === QUESTIONNAIRE_CONTENT_TYPE);
    if (!item || !item.Questionnaire) return null;
    return item.Questionnaire;
}

/**
 * 读取选项文案，兼容 Label/label 双写。
 */
function readOptionLabel(option: QuestionnaireOption): string {
    return option.Label ?? option.label ?? '';
}

/**
 * 读取选项描述，兼容 Description/description 双写。
 */
function readOptionDescription(option: QuestionnaireOption): string {
    return option.Description ?? option.description ?? '';
}

/**
 * 读取答案中选中的文案列表，兼容 SelectedLabels/selected_labels/selectedLabels 三种写法。
 */
export function readSelectedLabels(answer: QuestionnaireAnswer): string[] {
    return answer.SelectedLabels ?? answer.selected_labels ?? answer.selectedLabels ?? [];
}

/**
 * 读取答案对应的问题文本，兼容 Question/question 双写。
 */
export function readAnswerQuestion(answer: QuestionnaireAnswer): string {
    return answer.Question ?? answer.question ?? '';
}

/**
 * 判断问题是否为多选。
 */
export function isMultipleChoice(
    question: Pick<NormalizedQuestionnaireQuestion, 'type'>
): boolean {
    return question.type === QuestionnaireQuestionType.Multiple;
}

/**
 * 把后端下发的澄清结构归一化为渲染层可直接消费的结构。
 *
 * 转换规则（对齐 smart-webim 的消费方式）：
 *   - Index/index → id，缺省时回落为数组下标
 *   - Question/question → text
 *   - 选项的 Label/label、Description/description 归一
 *
 * @param questionnaire 后端下发的澄清内容体
 * @param fallbackTitle 标题缺省时使用的兜底文案（由调用方传入已翻译的文案）
 * @returns 归一化结果；入参为空时返回 null
 */
export function normalizeQuestionnaire(
    questionnaire: Questionnaire | null | undefined,
    fallbackTitle: string
): NormalizedQuestionnaire | null {
    if (!questionnaire) return null;

    const rawQuestions = questionnaire.Questions ?? questionnaire.questions ?? [];
    const rawAnswers = questionnaire.Answers ?? questionnaire.answers ?? [];
    const rawTitle = questionnaire.Title ?? questionnaire.title ?? '';

    const questions: NormalizedQuestionnaireQuestion[] = rawQuestions.map(
        (item, idx) => {
            const rawOptions = item.Options ?? item.options ?? [];
            const options: NormalizedQuestionnaireOption[] = rawOptions.map((opt) => ({
                label: readOptionLabel(opt),
                description: readOptionDescription(opt),
            }));
            return {
                id: item.Index ?? item.index ?? idx,
                text: item.Question ?? item.question ?? '',
                type: item.Type ?? item.type,
                required: item.Required ?? item.required,
                options,
            };
        }
    );

    return {
        title: rawTitle || fallbackTitle,
        questions,
        answers: rawAnswers,
    };
}

/**
 * 把历史消息中的 answers 映射为 ClassifyTag 的 defaultAnswers。
 *
 * 后端 answers 以「问题文本 + 选项文案」描述作答结果，需反查下标：
 *   - 通过 question 文本匹配到对应问题
 *   - 通过 label 文案匹配到对应选项下标
 *   - 单选产出 selectedIndex，多选产出 selectedIndices
 *
 * 特殊约定（对齐 smart-webim）：已提交但没有任何 answers（即用户点了「跳过」）时，
 * 返回一条 questionId 为 -1 的占位数据，目的是让 ClassifyTag 内部据此置为已提交态。
 *
 * @param normalized 归一化后的澄清数据
 * @param isSubmitted 该澄清是否已提交（含跳过）
 * @returns defaultAnswers 列表
 */
export function buildDefaultAnswers(
    normalized: NormalizedQuestionnaire | null,
    isSubmitted: boolean
): QuestionnaireDefaultAnswer[] {
    if (!normalized) return [];

    const { questions, answers } = normalized;

    // 已提交但无实际答案（跳过场景）：构造占位数据触发组件内部的已提交态
    if (isSubmitted && !answers.length) {
        return [{ questionId: -1, selectedIndex: -1 }];
    }
    if (!answers.length) return [];

    const result: QuestionnaireDefaultAnswer[] = [];

    answers.forEach((answer) => {
        const selectedLabels = readSelectedLabels(answer);
        if (!selectedLabels.length) return;

        // 通过问题文本匹配对应的问题
        const question = questions.find((q) => q.text === readAnswerQuestion(answer));
        if (!question) return;

        if (isMultipleChoice(question)) {
            // 多选：把所有选中文案映射为选项下标，未命中的丢弃
            const selectedIndices = selectedLabels
                .map((label) => question.options.findIndex((opt) => opt.label === label))
                .filter((idx) => idx !== -1);
            if (selectedIndices.length) {
                result.push({ questionId: question.id, selectedIndices });
            }
            return;
        }

        // 单选：只取第一个选中文案
        const selectedIndex = question.options.findIndex(
            (opt) => opt.label === selectedLabels[0]
        );
        if (selectedIndex !== -1) {
            result.push({ questionId: question.id, selectedIndex });
        }
    });

    return result;
}

/**
 * 把 ClassifyTag 的提交结果转换为上行所需的 answers。
 *
 * 单选也统一收敛为长度 1 的数组，与后端 SelectedLabels 的约定一致。
 * 若用户选择了「其他」，ClassifyTag 已把其文案替换为用户输入的文本，此处无需特殊处理。
 *
 * @param items ClassifyTag submit 事件回传的结果
 * @returns 上行 answers（PascalCase，与服务端协议一致）
 */
export function buildSubmitAnswers(
    items: QuestionnaireSubmitItem[]
): QuestionnaireAnswer[] {
    return items.map((item) => ({
        Question: item.questionText,
        SelectedLabels: item.isMulti
            ? item.selectedOptions ?? []
            : [item.selectedOption],
    }));
}

/**
 * 构造上行提交用的澄清内容体：保留后端原始字段，仅替换 answers。
 *
 * 同时写入 Answers 与 answers 两种键，以兼容服务端可能的解析差异；
 * 原始对象的其余字段（如 Title / Questions）原样透传。
 *
 * @param raw 后端下发的原始澄清内容体
 * @param answers 本次提交的答案
 * @returns 上行澄清内容体
 */
export function buildQuestionnairePayload(
    raw: Questionnaire,
    answers: QuestionnaireAnswer[]
): Questionnaire {
    const payload: Questionnaire = { ...raw, Answers: answers };
    // 原始数据使用小写键时同步覆盖，避免残留旧的空 answers
    if ('answers' in raw) {
        payload.answers = answers;
    }
    return payload;
}

/**
 * 计算已回答的问题数量。
 *
 * 规则（对齐 smart-webim，易错点）：
 *   - 过期未提交：视为已澄清 0 个问题
 *   - 其余情况直接取实际答案条数，**不能**兜底为问题总数，
 *     否则「跳过」会被误显示为全部已作答
 *
 * @param normalized 归一化后的澄清数据
 * @param options.localAnswers 提交瞬间的本地缓存答案，优先级高于历史 answers
 * @param options.isExpired 是否已过期
 * @param options.isSubmitted 是否已提交
 */
export function countAnswered(
    normalized: NormalizedQuestionnaire | null,
    options: {
        localAnswers?: QuestionnaireAnswer[] | null
        isExpired?: boolean
        isSubmitted?: boolean
    } = {}
): number {
    if (!normalized) return 0;
    const { localAnswers, isExpired = false, isSubmitted = false } = options;
    if (isExpired && !isSubmitted) return 0;
    const answers = localAnswers ?? normalized.answers ?? [];
    return answers.length;
}

/**
 * 构造已澄清摘要卡的数据。
 *
 * 无答案（跳过场景）时仍展示问题列表，答案位显示传入的「跳过」文案。
 *
 * @param normalized 归一化后的澄清数据
 * @param skippedLabel 跳过时展示的文案（由调用方传入已翻译的文案）
 * @param localAnswers 提交瞬间的本地缓存答案，优先级高于历史 answers
 */
export function buildSummaryItems(
    normalized: NormalizedQuestionnaire | null,
    skippedLabel: string,
    localAnswers?: QuestionnaireAnswer[] | null
): QuestionnaireSummaryItem[] {
    if (!normalized) return [];

    const answers = localAnswers ?? normalized.answers;

    if (!answers || !answers.length) {
        // 跳过场景：展示问题但答案位统一为「跳过」
        return normalized.questions.map((q) => ({
            question: q.text,
            answerLabel: skippedLabel,
        }));
    }

    return answers.map((answer) => ({
        question: readAnswerQuestion(answer),
        answerLabel: readSelectedLabels(answer).join('、'),
    }));
}
