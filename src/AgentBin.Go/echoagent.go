package main

import (
	"context"
	"fmt"
	"iter"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2asrv"
)

type echoAgent struct{}

var _ a2asrv.AgentExecutor = (*echoAgent)(nil)

func (e *echoAgent) Execute(_ context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	text := extractText(execCtx.Message)
	return func(yield func(a2a.Event, error) bool) {
		reply := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart(fmt.Sprintf("Echo: %s", text)))
		yield(reply, nil)
	}
}

func (e *echoAgent) Cancel(_ context.Context, _ *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {}
}
