/**
 * A probe for text that reads like instructions to an assistant, in what a
 * page hands the agent: its outline, its text, a search's matches, a dialog's
 * message, a tab's title. The rules, not the model, are the safety boundary;
 * the probe only makes the next side-effecting action ask the user, in every
 * mode, and warns the model. It looks for the shapes such text takes -
 * addressing the assistant, overriding its instructions, hiding from the user,
 * the markers of chat transcripts - in English and in Persian. It is meant to
 * catch the common cases cheaply, never to be complete.
 */

export type Probe = { hit: false } | { hit: true; snippet: string };

const SNIPPET_CHARS = 120;

const ENGLISH: RegExp[] = [
  /\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b[^.\n]{0,30}\b(instructions?|rules?|prompts?|guidelines|directives)\b/i,
  /\byou are (now |actually )?(an?|the) (ai|assistant|agent|language model|llm|chatbot|browser agent)\b/i,
  /\bas an ai( assistant| model| agent)?\b[^.\n]{0,40}\b(you (must|should|will|need to)|do|please)\b/i,
  /\b(system|developer|admin(istrator)?) (prompt|message|instruction|override)\b/i,
  /\b(assistant|ai|agent|claude|chatgpt|gpt|llm|model|copilot|gemini)\s*[:,-]\s*(please |now |you (must|should) )?(ignore|open|navigate|go to|visit|send|type|enter|click|forward|download|delete|run|execute|post|submit|transfer|pay)\b/i,
  /\b(important|urgent|attention|note)\b[^.\n]{0,20}\b(to|for) (the |any |all )?(ai|assistant|agent|bot|llm|model)s?\b/i,
  /\b(new|updated|real|actual|secret|hidden) (instructions?|task|goal|objective|mission)\b[^.\n]{0,20}\b(for you|is|are|:)/i,
  /\byour (new |real |actual |true |secret )?(task|instructions?|goal|objective|mission) (is|are) (now )?(to |:)/i,
  /\b(do not|don't|never) (tell|inform|show|alert|notify|mention (this|it) to) the (user|human|person)\b/i,
  /\bwithout (telling|asking|informing|alerting) the (user|human|person)\b/i,
  /\[\s*(inst|system|sys|assistant)\s*\]|<\|im_(start|end)\|>|<\/?(system|assistant|user)_?(prompt|message)?>|###\s*(system|instruction|assistant)\b|\bbegin (system|admin|hidden) (message|prompt|instructions)\b/i,
  /\b(this|the following) (is|are) (your|the) (new |real |only )?(instructions?|rules|orders)\b/i,
  /\bstop (following|obeying) (the |your )?(user|human)('s)?\b/i,
];

const PERSIAN: RegExp[] = [
  /(دستور(ات|العمل)?|قوانین|راهنما|پرامپت)(\s*\S+){0,3}\s*(قبلی|پیشین|بالا|قبل)(\s*\S+){0,4}\s*(نادیده|فراموش|رها|لغو)/,
  /(نادیده بگیر|فراموش کن|بی‌?خیال)(\s*\S+){0,5}\s*(دستور|قوانین|راهنما|پرامپت)/,
  /(تو|شما) (حالا |اکنون |یک |یه ){0,3}(هوش مصنوعی|دستیار|ربات|مدل زبانی|عامل|ایجنت) (هستی|هستید|باش|باشید)/,
  /به عنوان (یک |یه )?(هوش مصنوعی|دستیار|ربات|مدل زبانی)/,
  /(پرامپت|پیام|دستور) (سیستم|سیستمی|توسعه‌?دهنده|مدیر)/,
  /(دستیار|هوش مصنوعی|ربات|عامل|ایجنت|مدل)\s*[:،,-]\s*(لطفا|لطفاً|حالا|اکنون)?\s*(نادیده|باز کن|برو به|ارسال کن|بفرست|تایپ کن|وارد کن|کلیک کن|دانلود کن|حذف کن|اجرا کن|پرداخت کن|منتقل کن)/,
  /(مهم|فوری|توجه)(\s*\S+){0,3}\s*(برای|به) (هوش مصنوعی|دستیار|ربات|ایجنت|مدل)/,
  /(دستور|وظیفه|هدف|ماموریت|مأموریت)(‌| )?(جدید|واقعی|اصلی|مخفی|پنهان)(‌| )?(تو|شما|ات|تان)?\s*(این است|اینه|:)/,
  /(وظیفه|دستور|هدف)(‌|\s)?(ی|ی‌)?\s*(جدید|واقعی|اصلی)\s*(تو|شما)/,
  /(به|برای) کاربر (نگو|نگویید|نشان نده|اطلاع نده|چیزی نگو)/,
  /بدون (اطلاع|اجازه|گفتن به|پرسیدن از) کاربر/,
];

/** A short piece of the text around the match, on one line, for the card and the log. */
function snippetAround(text: string, index: number, length: number): string {
  const start = Math.max(0, index - 30);
  const end = Math.min(text.length, index + Math.max(length, 60) + 30);
  return text.slice(start, end).replace(/\s+/g, " ").trim().slice(0, SNIPPET_CHARS);
}

/** Whether `text` holds instruction-like text, with a snippet of the first hit. */
export function probeInjection(text: string): Probe {
  if (!text) return { hit: false };
  // Format characters and diacritics change how a word is drawn, not what it says.
  const plain = text.normalize("NFKC").replace(/\p{Cf}/gu, "").replace(/\p{M}/gu, "").replace(/[يى]/g, "ی").replace(/ك/g, "ک");
  for (const pattern of [...ENGLISH, ...PERSIAN]) {
    const match = pattern.exec(plain);
    if (match) return { hit: true, snippet: snippetAround(plain, match.index, match[0].length) };
  }
  return { hit: false };
}
