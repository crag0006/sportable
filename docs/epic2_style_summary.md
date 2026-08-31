# SportAble Epic2 设计基线

## 你队友已经完成了什么

- 已在 `sportable-feature-homepage` 中完成 `Epic1` 的首页原型。
- 入口页就是搜索页，采用左右分栏布局：
  - 左侧为深色搜索与筛选面板
  - 右侧为浅色结果展示区
- 已完成的前端能力包括：
  - 运动类型与 suburb/postcode 输入
  - 输入联想建议
  - 无障碍设施筛选
  - 距离阈值切换
  - 搜索结果列表
  - 未记录信息单独分组显示
  - 结果卡片中的设施状态展示
- 已建立一套明确的产品原则：
  - `Unknown is never a no`
  - 不使用综合无障碍评分
  - 每种设施分开显示
  - 缺失信息要明确说出，而不是默默隐藏

## 目前首页的视觉语言

### 布局

- 主结构：`split` 双栏布局
- 左栏宽度固定，右栏自适应
- 左栏承担输入、操作、品牌识别
- 右栏承担图片、结果、信息卡片

### 字体

- 主要字体为系统字体栈：
  - `system-ui`
  - `-apple-system`
  - `"Segoe UI"`
  - `sans-serif`
- 字体风格偏产品化、克制、可读性优先
- 标题较粗，正文与说明文字层级清晰

### 颜色

- 深蓝主背景：`#0c1c2d`
- 主按钮/交互蓝：`#14507a`
- 右侧浅背景：`#f3f6f5`
- 强调金色：`#ffbf47`
- 正向状态浅绿：`#e2f5ec`
- 风险/超限浅红：`#fde9e8`
- 未知状态浅灰：`#ecefef`
- 正文深色文字：`#1a1a1a` / `#102d32`
- 次级说明文字：`#66777a` 左右

### 组件风格

- 卡片：白底、细边框、轻阴影、圆角 8 到 10px
- 输入框：高度统一，边框清晰，圆角较小
- 按钮：
  - 实心主按钮
  - 描边次按钮
- 标签/状态块：
  - 使用浅底色 + 深色文字
  - 状态必须同时依赖文字和图标，不只靠颜色
- 信息结构偏“信息卡”而不是“营销海报”

### 间距与排版

- 左栏内边距较充足，保证表单不会拥挤
- 标题与分组之间有明显节奏
- 分区标题常用细分隔线
- 卡片内部信息块排列规则，强调“可扫读”

## 代码里真正构成设计基础的内容

目前最接近“设计基础”的不是单独某一个 `style` 文件，而是下面几部分一起组成：

- `frontend/src/pages/Home.css`
  - 页面整体布局
  - 左右区域背景
  - 表单、按钮、结果区域基础样式
- `frontend/src/components/SearchVenue.css`
  - 卡片样式
  - 状态色规范
  - 结果信息的展示方式
- `frontend/src/pages/Home.jsx`
  - 页面信息结构
  - 搜索流程与结果区层级
- `frontend/src/components/SearchVenue.jsx`
  - 设施信息如何拆分展示
  - 状态文案与按钮位置

## STYLE 文件是不是所有设计的基础

是基础，但还不够完整。

它目前更像是：

- 第一版页面样式规则
- 组件视觉语言
- 颜色与排版参考

它还不是完整设计系统，因为还缺少这些更高层规范：

- 统一的 design tokens
  - 颜色变量
  - 字号变量
  - 间距变量
  - 圆角变量
- 统一按钮、标签、表单、卡片的命名规范
- 页面模板级规范
  - 详情页如何分区
  - 地图页如何排版
  - 响应式规则如何复用
- 图标风格统一
  - 现在已有 SVG 和 emoji 混用，后续最好统一

## 对 Epic2 的延续建议

`Epic2` 应继续沿用以下核心规则：

- 继续保留深色左侧控制区 + 浅色右侧内容区
- 继续使用白色信息卡片承载核心内容
- 继续把每种无障碍设施拆开显示
- 继续明确展示：
  - 距离
  - 数据来源
  - 更新时间
  - 已知与未知边界
- 继续避免：
  - 综合评分
  - 模糊结论
  - 只靠颜色传递状态

## 我建议在你的分支中后续补出的基础文件

等你确认布局后，建议在 `sportable` 中补成下面这种结构：

- `frontend/src/styles/tokens.css`
  - 颜色、间距、圆角、阴影、字号
- `frontend/src/styles/base.css`
  - 全局字体、body、按钮、输入框基础规则
- `frontend/src/pages/VenueDetail.jsx`
  - Epic2 场馆详情页
- `frontend/src/pages/VenueDetail.css`
  - 场馆详情页样式
- `frontend/src/pages/Directions.jsx`
  - Epic2 路线页
- `frontend/src/pages/Directions.css`
  - 路线页样式
- `frontend/src/components/FacilityStatusCard.jsx`
  - 可复用设施状态组件
- `frontend/src/components/FacilityStatusCard.css`
  - 设施组件样式

## 当前判断

- 你队友没有把 `sportable-feature-data` 真正接进前端页面。
- 当前首页使用的是前端本地模拟数据 `src/data/Venues.js`。
- 因此你现在做 Epic2 页面时，可以先按同样方式用 mock data 完成界面，再等后续接口接入。
