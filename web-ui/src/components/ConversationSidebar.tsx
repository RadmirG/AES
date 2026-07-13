import type { Conversation } from "../types";

type Props = {
  conversations: Conversation[];
  activeConversationId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
};

export function ConversationSidebar({
  conversations,
  activeConversationId,
  onSelect,
  onNew,
  onDelete,
}: Props) {
  return (
    <aside className="conversationSidebar">
      <button className="newChatButton" onClick={onNew} type="button">
        New chat
      </button>

      <div className="conversationList">
        {conversations.map((conversation) => (
          <div
            className={
              conversation.id === activeConversationId
                ? "conversationItem active"
                : "conversationItem"
            }
            key={conversation.id}
            onClick={() => onSelect(conversation.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                onSelect(conversation.id);
              }
            }}
            role="button"
            tabIndex={0}
          >
            <span>{conversation.title}</span>
            <small>{formatTime(conversation.updatedAt)}</small>
            {conversations.length > 1 ? (
              <button
                className="deleteConversation"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(conversation.id);
                }}
                type="button"
              >
                Delete
              </button>
            ) : null}
          </div>
        ))}
      </div>
    </aside>
  );
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
