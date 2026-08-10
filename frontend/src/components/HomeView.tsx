import {useState} from "react";
import {HomeChatInput} from "./HomeChatInput";
import {HomeChatWindow, type HomeMessage} from "./HomeChatWindow";

export function HomeView({canUseCodeAssistant, onOpenAssistant}: {canUseCodeAssistant: boolean; onOpenAssistant: () => void}) {
  const [messages, setMessages] = useState<HomeMessage[]>([]);
  return (
    <section className="home-view" aria-labelledby="home-title">
      <div className="home-ambient home-ambient-one" />
      <div className="home-ambient home-ambient-two" />
      <div className="home-workspace">
        <header><span className="home-kicker">AURA WORKSPACE</span><h1 id="home-title">HOME</h1><p>AI Assistant</p></header>
        <HomeChatWindow messages={messages} />
        <HomeChatInput onSend={(content) => setMessages((current) => [...current, {id: crypto.randomUUID(), content}])} />
        {canUseCodeAssistant && <button className="home-assistant-link" onClick={onOpenAssistant}>Code Assistant 열기 <span>→</span></button>}
      </div>
    </section>
  );
}
