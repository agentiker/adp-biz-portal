/**
 * ADP chat protocol v2 data structures.
 */

export type NumberLike = number | string

export type RecordRole = 'user' | 'assistant'

export type ContentType =
  | 'text'
  | 'image'
  | 'widget'
  | 'file'
  | 'custom_variables'
  | 'widget_action'
  | 'json_text'
  | 'questionnaire'

export type MessageType =
  | 'reply'
  | 'thought'
  | 'tool_call'
  | 'task_execution'
  | 'recommendation'
  | 'notice'
  | 'question'

export interface Content {
  Type: ContentType
  Text?: string
  File?: FileInfo
  QuoteInfos?: QuoteInfo[]
  References?: Reference[]
  OptionCards?: string[]
  CustomParams?: string[]
  Sandbox?: Sandbox
  WebSearch?: WebSearch
  FileCollection?: FileCollection
  RelatedRecordId?: string
  Widget?: Widget
  CustomVariables?: { [key: string]: string }
  WidgetAction?: WidgetAction
  Questionnaire?: Questionnaire
}

export interface Image {
  QuoteInfos?: QuoteInfo[]
  References?: Reference[]
  OptionCards?: string[]
  CustomParams?: string[]
  Sandbox?: Sandbox
  WebSearch?: WebSearch
  FileCollection?: FileCollection
  RelatedRecordId?: string
  Widget?: Widget
}

export interface FileInfo {
  FileName: string
  FileSize: string
  FileUrl: string
  FileType: string
  Url?: string
  DocId?: string
}

export interface WidgetAction {
  WidgetId: string
  WidgetRunId: string
  ActionType: string
  Payload: string
  DocBizId?: string
}

export interface Widget {
  WidgetId: string
  WidgetRunId: string
  State: string
  Position?: number
  EncodedWidget: string
  View?: string
  Payload?: string
}

export interface QuoteInfo {
  Position: number
  Index: number
}

/**
 * 反问澄清（questionnaire）问题类型。
 * 与 smart-webim / gpt-demo 后端协议保持一致，不可变更。
 */
export const QuestionnaireQuestionType = {
  /** 单选 */
  Single: 1,
  /** 多选 */
  Multiple: 2,
} as const
export type QuestionnaireQuestionType =
  typeof QuestionnaireQuestionType[keyof typeof QuestionnaireQuestionType]

/**
 * 澄清问题的候选项。
 * 字段为 PascalCase，与 tcadp 其它 v2 协议结构保持一致。
 * 注意：smart-webim 在传输层做了 snake_case 归一，tcadp 无该转换层，
 * 直接消费服务端下发的 PascalCase，因此此处同时兼容小写写法以防御历史数据。
 */
export interface QuestionnaireOption {
  /** 选项文案 */
  Label?: string
  /** 选项补充描述 */
  Description?: string
  /** 选项文案（小写写法，兼容历史数据） */
  label?: string
  /** 选项补充描述（小写写法，兼容历史数据） */
  description?: string
}

/**
 * 单条澄清问题。
 */
export interface QuestionnaireQuestion {
  /** 问题序号，归一化后作为 questionId 使用 */
  Index?: number
  /** 问题文本 */
  Question?: string
  /** 问题类型：1=单选，2=多选 */
  Type?: QuestionnaireQuestionType
  /** 是否必答 */
  Required?: boolean
  /** 候选项列表；「其他」选项由前端自动追加，后端不下发 */
  Options?: QuestionnaireOption[]
  /** 以下为小写写法，兼容历史数据 */
  index?: number
  question?: string
  type?: QuestionnaireQuestionType
  required?: boolean
  options?: QuestionnaireOption[]
}

/**
 * 澄清答案（上行提交与历史回显共用同一结构）。
 * 后端以问题文本作为关联键，并以 SelectedLabels 承载选中的文案。
 */
export interface QuestionnaireAnswer {
  /** 对应的问题文本 */
  Question?: string
  /** 选中的选项文案；单选也统一为长度 1 的数组 */
  SelectedLabels?: string[]
  /** 以下为兼容写法（smart-webim 归一后的 snake_case / 驼峰） */
  question?: string
  selected_labels?: string[]
  selectedLabels?: string[]
}

/**
 * 反问澄清内容体，挂在 Content.Questionnaire 上。
 * 历史消息中 Answers 有值表示用户已提交过；为空则可能是未作答或已跳过。
 */
export interface Questionnaire {
  /** 卡片标题，缺省时前端回落为「问题澄清」 */
  Title?: string
  /** 问题列表 */
  Questions?: QuestionnaireQuestion[]
  /** 已提交的答案，用于历史回显 */
  Answers?: QuestionnaireAnswer[]
  /** 以下为小写写法，兼容历史数据 */
  title?: string
  questions?: QuestionnaireQuestion[]
  answers?: QuestionnaireAnswer[]
}

/** 归一化后的澄清选项，供 ClassifyTag 直接消费 */
export interface NormalizedQuestionnaireOption {
  label: string
  description: string
}

/** 归一化后的澄清问题，供 ClassifyTag 直接消费 */
export interface NormalizedQuestionnaireQuestion {
  /** 归一化后的问题标识，取自 index，缺省时回落为数组下标 */
  id: number
  /** 问题文本 */
  text: string
  /** 问题类型：1=单选，2=多选 */
  type?: QuestionnaireQuestionType
  /** 是否必答 */
  required?: boolean
  /** 候选项列表（不含前端追加的「其他」） */
  options: NormalizedQuestionnaireOption[]
}

/** 归一化后的澄清数据，供渲染层直接消费 */
export interface NormalizedQuestionnaire {
  title: string
  questions: NormalizedQuestionnaireQuestion[]
  answers: QuestionnaireAnswer[]
}

/**
 * ClassifyTag 历史回显入参。
 * 单选使用 selectedIndex，多选使用 selectedIndices。
 */
export interface QuestionnaireDefaultAnswer {
  questionId: number
  selectedIndex?: number
  selectedIndices?: number[]
}

/**
 * ClassifyTag 提交事件回传的单题结果。
 * 单选与多选字段同时提供，以兼容不同消费方（与 lke-component 行为一致）。
 */
export interface QuestionnaireSubmitItem {
  questionId: string
  questionText: string
  isMulti: boolean
  /** 单选选中文案；多选时取首个 */
  selectedOption: string
  /** 全部选中文案 */
  selectedOptions: string[]
  /** 单选选中下标；多选时取首个，无选中为 -1 */
  selectedIndex: number
  /** 全部选中下标 */
  selectedIndices: number[]
  /** 是否选中了「其他」选项 */
  isOther: boolean
}

/** 已澄清摘要卡的单行数据 */
export interface QuestionnaireSummaryItem {
  question: string
  answerLabel: string
}

export interface Reference {
  Index?: number
  Type?: number
  Name?: string
  Id?: string
  Url?: string
  DocBizId?: string
  QaBizId?: string
  ReferBizId?: string
  DocName?: string
  KnowledgeBizId?: string
  KnowledgeName?: string
  PageContent?: string
  OrgData?: string
  PageInfos?: number[]
  SheetInfos?: string[]
  DocType?: number
  Status?: string
  DocRefer?: DocRefer
  QaRefer?: QaRefer
  WebSearchRefer?: WebSearchRefer
}

export interface DocRefer {
  ReferBizId: string
  DocBizId: string
  DocId?: string
  DocName: string
  KnowledgeBizId: string
  KnowledgeId?: string
  KnowledgeName?: string
  ReferenceId?: string
  Url: string
}

export interface QaRefer {
  ReferBizId: string
  QaBizId: string
  KnowledgeBizId: string
  KnowledgeName?: string
}

export interface WebSearchRefer {
  Url: string
}

export interface Sandbox {
  Url?: string
  DisplayUrl?: string
  Content?: string
}

export interface WebSearch {
  Content: string
}

export interface FileCollection {
  MaxFileCount: number
  SupportedFileTypes: string[]
}

/** 聊天会话信息 */
export interface ChatConversation {
  Id: string
  AccountId: string
  Title: string
  LastActiveAt: number
  CreatedAt: number
  ApplicationId: string
}

/** 聊天会话请求参数 */
export interface ChatConversationProps {
  ConversationId?: string
  ShareId?: string
  LastRecordId?: string
}

/** 消息评分值枚举 */
export const ScoreValue = {
  Unknown: 0,
  Like: 1,
  Dislike: 2,
} as const
export type ScoreValue = typeof ScoreValue[keyof typeof ScoreValue]

export interface Record {
  Role: RecordRole
  RecordId: string
  RelatedRecordId?: string
  ConversationId: string
  Status: string
  StatusDesc: string
  Messages?: Message[]
  Procedures?: Procedure[]
  StatInfo?: StatInfo
  ExtraInfo?: RecordExtraInfo
  Score?: ScoreValue
}

export interface RecordExtraInfo {
  RequestId: string
  TraceId: string
  Elapsed: NumberLike
  StartTime: NumberLike
  IsFromSelf: boolean
  IsLlmGenerated?: boolean
  CanRating?: boolean
  CanFeedback?: boolean | null
  ReplyMethod?: number
  FromName?: string
  FromAvatar?: string
  HasRead?: boolean
}

export interface Message {
  Type: MessageType
  MessageId: string
  Name: string
  Title: string
  Icon?: string
  Status: string
  StatusDesc?: string
  Contents?: Content[]
  ExtraInfo?: MessageExtraInfo
}

export interface MessageExtraInfo {
  Elapsed: NumberLike
  StartTime: NumberLike
  AgentName?: string
  AgentIcon?: string
  ToolName?: string
  ToolIcon?: string
}

export interface Procedure {
  ParentMessageId?: string
  Name: string
  Title: string
  Status: string
  IntentCate?: string
  ResourceStatus?: number
  Type: string
  Knowledge?: Knowledge
  Workflow?: WorkflowProcedure
  Agent?: Agent
  StatInfos?: StatInfo[]
}

export interface Knowledge {
  Content: string
  System?: string
  RewriteQuery?: string
  CustomVariables?: string[]
  Histories?: History[]
  Outputs?: KnowledgeOutput[]
}

export interface History {
  Assistant?: string
  User?: string
}

export interface KnowledgeOutput {
  Type: number
  Content: string
}

export interface WorkflowProcedure {
  WorkflowId: string
  WorkflowName: string
  WorkflowReleaseTime: string
  WorkflowRunId: string
  Content: string
  Outputs: string[]
  OptionCardIndex?: OptionCardIndex
  OptionCards?: string[]
  RunNodes?: RunNode[]
}

export interface OptionCardIndex {
  RecordId: string
  Index: number
}

export interface RunNode {
  Elapsed: string
  NodeId: string
  NodeName: string
  NodeType: number
}

export interface Agent {
  Status: number
  Input?: string
  InputRef?: string
  Output?: string
  OutputRef?: string
  TaskOutput?: string
  TaskOutputRef?: string
  Reply?: string
  FailCode?: string
  FailMessage?: string
  BelongNodeId?: string
  IsCurrent?: boolean
  StatInfos?: StatInfo[]
  ModelName?: string
  Content?: string
  System?: string
  RewriteQuery?: string
  CustomVariables?: string[]
}

export interface StatInfo {
  Elapsed?: NumberLike
  StartTime?: NumberLike
  InputTokens?: NumberLike
  OutputTokens?: NumberLike
  TotalTokens?: NumberLike
  ModelName?: string
  Input?: string
  Output?: string
  Content?: string
  System?: string
  RewriteQuery?: string
  CustomVariables?: string[]
  FirstTokenCost?: NumberLike
  TotalCost?: NumberLike
}

export interface ErrorInfo {
  Code: number
  Message: string
  RequestId?: string
  TraceId?: string
  Elapsed?: NumberLike
  StartTime?: NumberLike
}

export interface ConversationPayload extends ChatConversation {
  IsNewConversation?: boolean
}

export interface RequestAckEvent {
  Type: 'request_ack'
  RequestAck: Record
}

export interface ConversationEvent {
  Type: 'conversation'
  Payload: ConversationPayload
}

export interface ResponseCreatedEvent {
  Type: 'response.created'
  Response: Record
}

export interface ResponseProcessingEvent {
  Type: 'response.processing'
  Response: Record
}

export interface ResponseCompletedEvent {
  Type: 'response.completed'
  Response: Record
}

export interface MessageAddedEvent {
  Type: 'message.added'
  Message: Message
}

export interface MessageProcessingEvent {
  Type: 'message.processing'
  MessageId: string
  Message: Message
}

export interface MessageDoneEvent {
  Type: 'message.done'
  MessageId: string
  Message: Message
}

export interface ContentAddedEvent {
  Type: 'content.added'
  MessageId: string
  ContentIndex: number
  Content: Content
}

export interface ReferenceAddedEvent {
  Type: 'reference.added'
  MessageId: string
  ContentIndex: number
  Reference: Reference
  Timestamp?: NumberLike
}

export interface TextDeltaEvent {
  Type: 'text.delta'
  MessageId: string
  ContentIndex: number
  Text: string
}

export interface ErrorEvent {
  Type: 'error'
  Error: ErrorInfo
  Timestamp?: string
  RecordId?: string
}

export type SseEvent =
  | ConversationEvent
  | RequestAckEvent
  | ResponseCreatedEvent
  | ResponseProcessingEvent
  | ResponseCompletedEvent
  | MessageAddedEvent
  | MessageProcessingEvent
  | MessageDoneEvent
  | ContentAddedEvent
  | ReferenceAddedEvent
  | TextDeltaEvent
  | ErrorEvent
