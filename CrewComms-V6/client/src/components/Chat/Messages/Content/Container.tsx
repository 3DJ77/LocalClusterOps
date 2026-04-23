import { TMessage } from 'librechat-data-provider';
import { cn } from '~/utils';
import Files from './Files';

const Container = ({
  children,
  message,
  isCreatedByUser,
}: {
  children: React.ReactNode;
  message?: TMessage;
  isCreatedByUser?: boolean;
}) => {
  const isUserMessage = isCreatedByUser === true || message?.isCreatedByUser === true;

  return (
    <div
      className={cn(
        'text-message flex min-h-[20px] flex-col gap-3 overflow-visible rounded-lg border px-4 py-3 shadow-[0_10px_24px_rgba(0,10,30,0.24)] [.text-message+&]:mt-5',
        isUserMessage
          ? 'ml-auto items-end border-[#3b6fb3] bg-[#0d356b] text-[#f5f9ff]'
          : 'mr-auto items-start border-[#274b7d] bg-[#092a5a] text-[#dbe9ff]',
      )}
      dir="auto"
    >
      {isUserMessage && <Files message={message} />}
      {children}
    </div>
  );
};

export default Container;
