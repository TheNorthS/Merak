import { CheckCircle, Clock, Loader2, XCircle } from 'lucide-react'


export function NodeStatus({ status }: { status: string }) {
  if (status === 'running') {
    return <Loader2 size={14} className="animate-spin text-foreground" />
  }
  if (status === 'completed') {
    return <CheckCircle size={14} className="text-green-400" />
  }
  if (status === 'failed') {
    return <XCircle size={14} className="text-red-400" />
  }
  return <Clock size={14} className="text-muted-foreground" />
}
