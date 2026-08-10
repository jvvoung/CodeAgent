export type HomeMessage = {id: string; content: string};

export function HomeChatWindow({messages}: {messages: HomeMessage[]}) {
  return (
    <div className="home-chat-window" aria-live="polite">
      {messages.length ? messages.map((message) => <div className="home-chat-message" key={message.id}><span>나</span><p>{message.content}</p></div>) : <div className="home-chat-empty"><span>✦</span><strong>무엇을 도와드릴까요?</strong><p>메시지를 입력하면 이곳에 대화가 표시됩니다.</p></div>}
    </div>
  );
}
