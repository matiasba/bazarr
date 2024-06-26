import { useCallback, useState } from "react";
import { UseMutationResult } from "react-query";
import { Action } from "../inputs";
import { ActionProps } from "../inputs/Action";

type MutateActionProps<DATA, VAR> = Omit<
  ActionProps,
  "onClick" | "loading" | "color"
> & {
  mutation: UseMutationResult<DATA, unknown, VAR>;
  args: () => VAR | null;
  onSuccess?: (args: DATA) => void;
  onError?: () => void;
  noReset?: boolean;
};

function MutateAction<DATA, VAR>({
  mutation,
  noReset,
  onSuccess,
  onError,
  args,
  ...props
}: MutateActionProps<DATA, VAR>) {
  const { mutateAsync } = mutation;

  const [isLoading, setLoading] = useState(false);

  const onClick = useCallback(async () => {
    setLoading(true);
    try {
      const argument = args();
      if (argument !== null) {
        const data = await mutateAsync(argument);
        onSuccess?.(data);
      } else {
        onError?.();
      }
    } catch (error) {
      onError?.();
    }
    setLoading(false);
  }, [args, mutateAsync, onError, onSuccess]);

  return <Action {...props} loading={isLoading} onClick={onClick}></Action>;
}

export default MutateAction;
