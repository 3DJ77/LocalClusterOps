import { useEffect, useMemo } from 'react';
import { useRecoilValue } from 'recoil';
import { FileSources, LocalStorageKeys } from 'librechat-data-provider';
import type { ExtendedFile } from '~/common';
import DragDropWrapper from '~/components/Chat/Input/Files/DragDropWrapper';
import { EditorProvider, ArtifactsProvider } from '~/Providers';
import { useDeleteFilesMutation } from '~/data-provider';
import Artifacts from '~/components/Artifacts/Artifacts';
import ConsoleLayout from '~/components/Commander/ConsoleLayout';
import { useSetFilesToDelete } from '~/hooks';
import store from '~/store';

export default function Presentation({ children }: { children: React.ReactNode }) {
  const artifacts = useRecoilValue(store.artifactsState);
  const artifactsVisibility = useRecoilValue(store.artifactsVisibility);

  const setFilesToDelete = useSetFilesToDelete();

  const { mutateAsync } = useDeleteFilesMutation({
    onSuccess: () => {
      console.log('Temporary Files deleted');
      setFilesToDelete({});
    },
    onError: (error) => {
      console.log('Error deleting temporary files:', error);
    },
  });

  useEffect(() => {
    const filesToDelete = localStorage.getItem(LocalStorageKeys.FILES_TO_DELETE);
    const map = JSON.parse(filesToDelete ?? '{}') as Record<string, ExtendedFile>;
    const files = Object.values(map)
      .filter(
        (file) =>
          file.filepath != null && file.source && !(file.embedded ?? false) && file.temp_file_id,
      )
      .map((file) => ({
        file_id: file.file_id,
        filepath: file.filepath as string,
        source: file.source as FileSources,
        embedded: !!(file.embedded ?? false),
      }));

    if (files.length === 0) {
      return;
    }
    mutateAsync({ files });
  }, [mutateAsync]);

  const artifactsElement = useMemo(() => {
    if (artifactsVisibility === true && Object.keys(artifacts ?? {}).length > 0) {
      return (
        <ArtifactsProvider>
          <EditorProvider>
            <Artifacts />
          </EditorProvider>
        </ArtifactsProvider>
      );
    }
    return null;
  }, [artifactsVisibility, artifacts]);

  return (
    <DragDropWrapper className="local-chat-surface relative flex w-full grow overflow-hidden bg-[#001933] [--border-heavy:#3b5f93] [--border-light:#1b3766] [--border-medium:#274b7d] [--border-xheavy:#77a8f7] [--presentation:#001933] [--surface-active-alt:#164a8a] [--surface-active:#123c74] [--surface-chat:#062451] [--surface-hover-alt:#17487f] [--surface-hover:#123c74] [--surface-primary-alt:#031733] [--surface-primary:#061d42] [--surface-secondary-alt:#0d356b] [--surface-secondary:#092a5a] [--surface-tertiary:#123c74] [--text-primary:#dbe9ff] [--text-secondary-alt:#8198bb] [--text-secondary:#9fb4d4] [--text-tertiary:#687f9f]">
      <ConsoleLayout artifacts={artifactsElement}>{children}</ConsoleLayout>
    </DragDropWrapper>
  );
}
