import {FormEvent, useState} from "react";

export function HomeChatInput({onSend}: {onSend: (message: string) => void}) {
  const [message, setMessage] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = message.trim();
    if (!value) return;
    onSend(value);
    setMessage("");
  };
  return <form className="home-chat-input" onSubmit={submit}><input aria-label="HOME 메시지" placeholder="메시지를 입력하세요..." value={message} onChange={(event) => setMessage(event.target.value)} /><button className="primary" type="submit" disabled={!message.trim()}>전송</button></form>;
}
